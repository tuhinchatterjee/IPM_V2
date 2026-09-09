"""The Playbook in a real browser.

Chromium, the built Next.js app, the real backend, a real sign-in form. No
component harness and no mocked fetch: what these assert is what a committee
member would see on the screen.
"""

from __future__ import annotations

import os
import re
import sys

from playwright.sync_api import sync_playwright

APP = os.environ.get("CREDITPROBE_APP", "http://127.0.0.1:3000")
SHOTS = os.environ.get(
    "CREDITPROBE_SHOTS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots"))

FAILURES: list[str] = []
NOTES: list[str] = []


def check(journey: str, label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {journey} :: {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{journey} :: {label} -- {detail}")
    return ok


def main() -> int:
    import pathlib

    pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None,
            args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(f"console:{m.text}")
                if m.type == "error" else None)

        # ------------------------------------------------------------ P
        print("\nJourney P — signing in and reaching the Playbook")
        page.goto(f"{APP}/playbook", wait_until="networkidle")
        signed_out = page.content()
        check("P", "signed out, the Playbook is not readable",
              "Retail Credit Risk Committee" not in signed_out,
              "a committee name rendered before sign-in")

        check("P", "signed out, a sign-in form is what is offered",
              page.locator("#username").count() == 1
              and page.locator("#password").count() == 1,
              "the application shell rendered instead of a sign-in screen")

        page.fill("#username", "alex.rahman")
        page.fill("#password", "creditprobe-demo")
        page.click("button[type='submit']")
        page.wait_for_selector("text=Sign out", timeout=20000)
        check("P", "the sign-in form accepted the demo account",
              page.locator("#password").count() == 0, page.url)

        # Errors from before signing in are the 401 the gate is SUPPOSED to
        # get. What matters is what happens once somebody is in.
        errors.clear()

        page.goto(f"{APP}/playbook", wait_until="networkidle")
        page.wait_for_selector("text=Retail Credit Risk Committee", timeout=30000)
        body = page.inner_text("body")
        page.screenshot(path=f"{SHOTS}/p-playbook.png", full_page=True)
        for name in ("Retail Credit Risk Committee",
                     "Corporate Credit Committee",
                     "IFRS 9 Impairment Committee"):
            check("P", f"{name} is on the Playbook", name in body,
                  body[:200].replace("\n", " "))

        # ------------------------------------------------------------ Q
        print("\nJourney Q — opening a committee and its pack")
        page.goto(f"{APP}/playbook/committees", wait_until="networkidle")
        page.wait_for_selector("text=Retail Credit Risk Committee", timeout=30000)
        page.click("text=Retail Credit Risk Committee")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        committee = page.inner_text("body")
        page.screenshot(path=f"{SHOTS}/q-committee.png", full_page=True)
        check("Q", "the committee page names its cadence",
              "Monthly" in committee or "MONTHLY" in committee, page.url)
        check("Q", "the committee page lists its packs",
              "2025-01" in committee or "2024-12" in committee,
              committee[:200].replace("\n", " "))

        # `New pack` also lives under /playbook/packs/, so match a pack id.
        link = page.locator(
            "a[href*='/playbook/packs/']:not([href*='/new'])").first
        check("Q", "a pack can be opened from the committee",
              link.count() > 0 if hasattr(link, "count") else True)
        link.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1800)
        pack = page.inner_text("body")
        page.screenshot(path=f"{SHOTS}/q-pack.png", full_page=True)
        NOTES.append(f"Q: pack page {page.url}")

        # ------------------------------------------------------------ R
        print("\nJourney R — the pack shows real figures, not placeholders")
        check("R", "the pack names its sections",
              "Book performance" in pack, pack[:200].replace("\n", " "))
        percents = re.findall(r"\d+\.\d\d%", pack)
        check("R", "governed percentages are rendered", len(percents) >= 3,
              ", ".join(percents[:6]))
        check("R", "no figure shows as a bare 0.0%",
              "0.00%" not in percents, ", ".join(percents[:8]))
        check("R", "readiness is shown as a percentage",
              re.search(r"\b\d{1,3}%", pack) is not None)
        NOTES.append(f"R: figures on screen — {', '.join(sorted(set(percents))[:8])}")

        # ------------------------------------------------------------ S
        print("\nJourney S — a number opens to its working")
        opened = False
        for label in ("Working", "How this was calculated", "Show working",
                      "Basis"):
            found = page.get_by_text(label, exact=False)
            if found.count():
                found.first.click()
                page.wait_for_timeout(900)
                opened = True
                break
        after = page.inner_text("body")
        page.screenshot(path=f"{SHOTS}/s-working.png", full_page=True)
        check("S", "the working can be opened", opened,
              "no control on the page opened a figure's working")
        check("S", "the working names the metric and period",
              "retail.default_rate" in after or "2025-01" in after)
        check("S", "the working shows a formula hash",
              re.search(r"[0-9a-f]{8,}", after) is not None)
        NOTES.append("S: working panel opened and shows the metric basis")

        # ------------------------------------------------------------ T
        print("\nJourney T — the screen carries no unhandled error")
        real = [e for e in errors
                if "favicon" not in e and "404" not in e
                and "Download the React DevTools" not in e]
        check("T", "no page error and no console error", not real,
              "; ".join(real[:3]))
        # Not a blanket search for the word: the readiness gate legitimately
        # SAYS "the pack has a placeholder where a figure should be" when a
        # figure is missing, and that sentence is the product working. What
        # must not appear is unfinished scaffolding.
        unfinished = re.search(
            r"\bTODO\b|\bFIXME\b|Coming soon|Lorem ipsum|Not implemented"
            r"|\bWIP\b|\[placeholder\]", after, re.I)
        check("T", "nothing on screen is unfinished scaffolding",
              unfinished is None, unfinished.group(0) if unfinished else "")

        browser.close()

    print("\n" + "=" * 68)
    for n in NOTES:
        print("  note: " + n)
    print(f"  screenshots in {SHOTS}")
    print("=" * 68)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nAll browser checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
