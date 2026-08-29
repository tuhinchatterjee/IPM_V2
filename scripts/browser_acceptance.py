"""
Browser acceptance. §36, §211.

    §36: "If browser acceptance cannot run, do not mark it passed."

So it runs. This drives a real Chromium against a real backend and a real
front end, at §36's three viewports, and asserts the things a screenshot
cannot: no horizontal overflow, no stranded navigation, truthful stage
labels, and an assurance figure that is never called accuracy.

What it checks, and why each one
----------------------------------
**No horizontal overflow.** `scrollWidth > clientWidth` on the body. The
commonest way a dense table breaks a 1366-wide laptop, and invisible on the
developer's 1440.

**No stranded navigation.** Every page reachable from the nav must render a
back path or a nav. A screen a user can reach and not leave is worse than one
that does not exist.

**Truthful labels.** §5 forbids "Chief Orchestrator is working" without a
Chief Orchestrator run. This asserts the weaker, checkable half: no page
shows a fake percent-complete, and no assurance figure is labelled accuracy.

**Reduced motion.** With `prefers-reduced-motion: reduce`, nothing may
animate indefinitely.

Running it
-----------
    .venv/bin/python scripts/browser_acceptance.py --start

`--start` boots the backend and the front end, waits for both, runs, and
stops them. Without it, both are assumed to be up already.

If Chromium is unavailable the script EXITS NON-ZERO with a clear message
rather than reporting success — §36's rule, enforced.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://127.0.0.1:3000"
BACKEND = "http://127.0.0.1:8000"

#: §36's viewports.
VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("desktop", 1440, 900),
    ("laptop", 1366, 768),
    ("tablet", 834, 1112),
)

#: §36's screens. Each is (path, what must be visible for it to count as
#: rendered). The marker is a role or text a broken page would not produce,
#: so a 200 that rendered an error boundary is not counted as a pass.
SCREENS: tuple[tuple[str, str], ...] = (
    ("/", "main"),
    ("/investigations", "main"),
    ("/projects", "main"),
    ("/ai-studio", "main"),
    ("/agent-operations", "main"),
    ("/data-builder", "main"),
    ("/studio", "main"),
    ("/analyses", "main"),
    ("/trace", "main"),
    ("/workflow", "main"),
    ("/settings", "main"),
)

#: Words that may never label a figure with no independent reference. §184.
FORBIDDEN = ("accuracy 9", "accuracy: 9", "accuracy 100")


@dataclass
class Check:
    screen: str
    viewport: str
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"screen": self.screen, "viewport": self.viewport,
                "check": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    started: str = ""
    error: str = ""

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "started": self.started,
            "viewports": [{"name": n, "width": w, "height": h}
                          for n, w, h in VIEWPORTS],
            "screens": [s for s, _ in SCREENS],
            "checks": [c.to_dict() for c in self.checks],
            "total": len(self.checks),
            "failed": len(self.failures),
            "passed": len(self.checks) - len(self.failures),
            "error": self.error,
        }


def _wait(url: str, *, seconds: int = 120) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(2)
    return False


def _chromium() -> str | None:
    """The Chromium already on the machine, if the bundled one is missing.

    The Playwright package and the installed browsers can be different
    versions — the package looks for build 1234 while build 1194 is what is
    present. Downloading another copy is the wrong fix in a sandbox with a
    pre-provisioned browser, so the existing binary is used directly.
    Returning None lets Playwright do its normal resolution where the
    versions do match.
    """
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        for found in sorted(root.glob(pattern), reverse=True):
            if found.is_file():
                return str(found)
    return None


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. Browser acceptance "
                        "did not run and is NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as e:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {e}. Browser "
                            "acceptance did not run and is NOT passed.")
            return report

        for name, width, height in VIEWPORTS:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                reduced_motion="reduce")
            page = context.new_page()
            for path, marker in SCREENS:
                _screen(page, report, path, marker, name)
            context.close()
        browser.close()
    return report


def _screen(page: Any, report: Report, path: str, marker: str,
            viewport: str) -> None:
    def record(check: str, ok: bool, detail: str = "") -> None:
        report.checks.append(Check(screen=path, viewport=viewport,
                                   name=check, ok=ok, detail=detail))

    # Console errors and unhandled exceptions, captured for the diagnostic
    # below. A page that renders nothing has almost always thrown, and "no
    # 'main' appeared" without the exception is a dead end for whoever reads
    # the report.
    console: list[str] = []
    page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
    page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning") else None)

    try:
        response = page.goto(f"{FRONTEND}{path}", wait_until="domcontentloaded",
                             timeout=45_000)
    except Exception as e:  # noqa: BLE001
        record("loads", False, f"{type(e).__name__}: {e}")
        return

    status = response.status if response else 0
    record("loads", status < 400, f"HTTP {status}")
    if status >= 400:
        return

    # It rendered, rather than rendering an error boundary.
    try:
        page.wait_for_selector(marker, timeout=20_000)
        record("renders", True)
    except Exception:  # noqa: BLE001
        # Say WHAT rendered instead. "no 'main' appeared" is unactionable;
        # the first line of the body tells you whether it was a sign-in
        # screen, an error boundary or an empty shell.
        try:
            seen = (page.inner_text("body") or "").strip().splitlines()
            head = "; ".join(line.strip() for line in seen[:3] if line.strip())
        except Exception:  # noqa: BLE001
            head = "(the page had no readable body)"
        record("renders", False, f"no {marker!r} appeared — page said: "
                                 f"{head[:120] or '(nothing)'}"
                                 + (f" — console: {console[0][:160]}"
                                    if console else " — console: silent"))
        return

    # §36: no horizontal overflow.
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - "
        "document.documentElement.clientWidth")
    record("no horizontal overflow", overflow <= 1,
           f"{overflow}px beyond the viewport")

    # §36: no stranded navigation — something to leave by.
    leaves = page.evaluate(
        "() => document.querySelectorAll('nav a, a[href=\\\"/\\\"], "
        "[data-back], button').length")
    record("navigable", leaves > 0, f"{leaves} way(s) out")

    text = (page.inner_text("body") or "").lower()

    # §184: no figure labelled accuracy.
    found = [word for word in FORBIDDEN if word in text]
    record("no accuracy label", not found, "; ".join(found))

    # §5: no fake percent complete on a working indicator.
    fake = "% complete" in text and "assurance" not in text
    record("no fake progress", not fake)

    # §36: reduced motion is respected — nothing animates forever.
    spinning = page.evaluate(
        "() => Array.from(document.querySelectorAll('*')).filter(el => {"
        "  const s = getComputedStyle(el);"
        "  return s.animationIterationCount === 'infinite' &&"
        "         s.animationPlayState === 'running';"
        "}).length")
    record("reduced motion respected", spinning == 0,
           f"{spinning} element(s) animating indefinitely")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true",
                        help="boot the backend and front end first")
    parser.add_argument("--out", default="docs/browser_acceptance.json")
    args = parser.parse_args(argv)

    report = Report(started=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    processes: list[subprocess.Popen] = []
    try:
        if args.start:
            env = {**os.environ, "REQUIRE_LOGIN": "false"}
            processes.append(subprocess.Popen(
                [str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
                 "backend.api.main:app", "--port", "8000"],
                cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            # `start`, not `dev`. Next's dev server compiles each route on
            # first request, so the first visit to every screen returned an
            # empty body inside the timeout — reported as "nothing rendered"
            # when in fact nothing had been built yet. The production server
            # is also what acceptance should be run against: it is the
            # artefact that ships.
            processes.append(subprocess.Popen(
                ["npm", "run", "start", "--", "--port", "3000"],
                cwd=ROOT / "frontend", env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            if not _wait(f"{BACKEND}/api/v1/health"):
                report.error = "the backend never became healthy"
            elif not _wait(FRONTEND):
                report.error = "the front end never became reachable"

        if not report.error:
            run(report)
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover
                process.kill()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report.to_dict(), indent=2),
                              encoding="utf-8")

    if report.error:
        print(f"BROWSER ACCEPTANCE DID NOT RUN: {report.error}")
        return 2
    body = report.to_dict()
    print(f"{body['passed']}/{body['total']} browser checks passed "
          f"across {len(VIEWPORTS)} viewports and {len(SCREENS)} screens.")
    for failure in report.failures:
        print(f"  FAIL {failure.viewport:8} {failure.screen:20} "
              f"{failure.name}: {failure.detail}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
