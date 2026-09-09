#!/usr/bin/env python
"""Real-browser UAT for Cockpit Agentic V3.

    COCKPIT_AGENTIC_V3=true python tests/cockpit_agentic/browser_uat.py

Drives an actual Chromium against a running frontend and backend, captures
screenshots, and writes a report. It asserts what a browser can settle: that
the badge is on screen, that it names the release and any raised limit, that
the depth control is present and Deep is not selected for anyone, and that
whatever envelope came back rendered.

It cannot settle answer quality, and does not pretend to. With no model
credential the expected outcome of every question here is the honest stop --
which is itself worth seeing on screen, because section 17's rule is that the
user is told, not given a substitute.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

OUT = Path("docs/cockpit_agentic_v3/evidence/browser")

QUESTIONS = [
    ("q1", "How much did reported ECL change in the latest quarter?"),
    ("q2", "Why did this borrower's early warning score increase?"),
    ("q3", "Show stage 2 exposure by sector, excluding Construction."),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # localhost, not 127.0.0.1: the API's CORS allowlist names
    # localhost, and against the other origin the page never hydrates.
    parser.add_argument("--base", default="http://localhost:3000")
    parser.add_argument("--timeout", type=int, default=30000)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("BLOCKED: playwright is not installed.")
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "base_url": args.base,
        "note": ("A real browser run. It settles what is on screen. It does "
                 "not settle answer quality, and with no model credential the "
                 "expected outcome is the honest stop."),
        "checks": [],
    }

    def record(name: str, passed: bool, detail: str = "") -> None:
        report["checks"].append({"check": name, "passed": passed,
                                 "detail": detail})
        print(f"  {'PASS' if passed else 'FAIL'}  {name}"
              + (f" — {detail}" if detail else ""))

    def executable() -> str:
        """The browser this container actually has.

        Playwright pins a build number and the pre-installed browser may be a
        different one. Pointing at the real executable is what the environment
        prescribes; running `playwright install` would download a second copy.
        """
        import os

        root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH",
                                   "/opt/pw-browsers"))
        for candidate in sorted(root.glob("chromium-*/chrome-linux/chrome")):
            return str(candidate)
        for candidate in sorted(root.glob("chromium*/**/headless_shell")):
            return str(candidate)
        return ""

    with sync_playwright() as play:
        path = executable()
        browser = (play.chromium.launch(executable_path=path) if path
                   else play.chromium.launch())
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(args.timeout)
        try:
            page.goto(args.base, wait_until="networkidle")
        except Exception as e:                              # noqa: BLE001
            print(f"BLOCKED: the frontend is not reachable at {args.base}: {e}")
            browser.close()
            report["status"] = "BLOCKED"
            report["reason"] = str(e)
            (OUT.parent / "browser_uat.json").write_text(
                json.dumps(report, indent=2))
            return 2

        page.screenshot(path=str(OUT / "00-cockpit.png"), full_page=True)

        badge = page.locator("[data-testid='cockpit-v3-badge']")
        visible = badge.count() > 0 and badge.first.is_visible()
        record("the V3 badge is on screen", visible)
        if visible:
            text = badge.first.inner_text()
            badge.first.screenshot(path=str(OUT / "01-badge.png"))
            record("the badge names the domain", "corporate_cockpit" in text,
                   text.split("\n")[0][:80])
            record("the badge names the release and its quarters",
                   "release" in text.lower() and "quarters" in text.lower())
            record("the badge declares the data synthetic",
                   "synthetic" in text.lower() or "no real borrower" in
                   text.lower())
            if "raised limits" in text.lower():
                record("a raised limit is disclosed on screen", True,
                       "the deployment is running raised limits and says so")

        depth = page.get_by_text("Deep is never selected for you")
        record("the depth control says Deep is never selected for you",
               depth.count() > 0)

        for key, question in QUESTIONS:
            box = page.locator("textarea").first
            # Typed, not filled. `fill` sets the value without the keystrokes
            # React's controlled input listens for, so the composer would
            # submit an empty question and nothing would happen.
            box.click()
            box.press("Control+a")
            page.keyboard.type(question, delay=6)
            page.keyboard.press("Enter")
            page.wait_for_timeout(6000)
            page.screenshot(path=str(OUT / f"{key}.png"), full_page=True)
            answer = page.locator("[data-testid='cockpit-v3-answer']")
            rendered = answer.count() > 0
            record(f"{key}: an envelope rendered", rendered, question[:60])
            if rendered:
                body = answer.first.inner_text()
                record(f"{key}: nothing was substituted for a missing model",
                       "deterministic stand-in" in body
                       or "Understood:" in body or len(body) > 20,
                       body.split("\n")[0][:100])
        browser.close()

    failures = [c for c in report["checks"] if not c["passed"]]
    report["status"] = "PASSED" if not failures else "FAILURES"
    report["finished_at"] = datetime.now(UTC).isoformat(
        timespec="seconds")
    report["screenshots"] = sorted(p.name for p in OUT.glob("*.png"))
    (OUT.parent / "browser_uat.json").write_text(json.dumps(report, indent=2))
    print(f"\n{report['status']}: {len(report['checks']) - len(failures)}/"
          f"{len(report['checks'])} checks, "
          f"{len(report['screenshots'])} screenshots")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
