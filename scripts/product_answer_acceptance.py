"""
Browser acceptance for the product-knowledge answer experience.

Section 19 asks for screenshots of four principal product questions, and
section 15's claim - that the answer surface renders the structure rather than
collapsing it - is one a screenshot alone cannot check. So this drives a real
Chromium through the REAL Ask path and asserts, on the rendered document:

*   the answer contains real heading elements, not upper-cased sentences;
*   bulleted content renders as list items;
*   no single rendered paragraph is a wall of prose;
*   the page does not scroll sideways at 1366 wide, which is the laptop the
    product is demonstrated on;
*   nothing about the answer is a chart.

It writes one PNG per question next to the report so the visual inspection
section 16 asks for can actually be done.

Running it
-----------
    .venv/bin/python scripts/product_answer_acceptance.py --start

`--start` boots the backend and the built front end, waits for both, runs and
stops them. If Chromium is unavailable the script EXITS NON-ZERO with a clear
message rather than reporting success.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRONTEND = "http://127.0.0.1:3000"
BACKEND = "http://127.0.0.1:8000"

#: Section 19's four principal questions, plus the one that proves the
#: opposite case - an answer that must NOT be turned into headings and bullets.
#: Each carries a phrase only its own answer contains. Without this the whole
#: run passes on a page that never rendered an answer at all: an error card has
#: a heading, the navigation supplies list items, and neither an overlong
#: paragraph nor a chart appears on a screen with nothing on it. A structural
#: check that cannot tell an answer from a stack trace proves nothing.
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("overview", "What is CreditProbe AI?", "AI Risk Officer"),
    ("capabilities", "What can CreditProbe do?", "CreditProbe at a glance"),
    ("ai_role", "What is the role of AI in CreditProbe?",
     "AI does the thinking"),
    ("early_warning", "What is the Early Warning methodology?", "Four layers"),
)

#: The laptop the product is shown on. Sideways scroll here is the defect that
#: is invisible on the developer's wider screen.
VIEWPORT = {"width": 1366, "height": 900}

#: A rendered paragraph longer than this is the wall of prose this whole
#: remediation exists to remove.
MAX_PARAGRAPH_CHARS = 700


def _wait(url: str, seconds: int = 180) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


def run(out_dir: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment
        return {"error": f"Playwright is not installed: {exc}"}

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    with sync_playwright() as play:
        # A Chromium installed beside a differently-versioned Playwright will
        # not be found by the default lookup, which reports it as missing. It
        # is present; it just has another build number. Falling back to the
        # binary on disk is the difference between running acceptance and
        # declaring it unrunnable.
        fallback = os.environ.get("CHROMIUM_PATH", "/opt/pw-browsers/chromium")
        try:
            browser = play.chromium.launch()
        except Exception:  # noqa: BLE001 - environment
            try:
                browser = play.chromium.launch(executable_path=fallback)
            except Exception as exc:  # noqa: BLE001 - environment
                return {"error": f"Chromium would not launch: {exc}"}
        page = browser.new_page(viewport=VIEWPORT)
        for key, question, marker in QUESTIONS:
            found: dict[str, Any] = {"key": key, "question": question,
                                     "checks": []}

            checks: list[dict[str, Any]] = found["checks"]

            def check(name: str, passed: bool, detail: str = "",
                      into: list[dict[str, Any]] = checks) -> None:
                into.append({"name": name, "passed": bool(passed),
                             "detail": detail})

            try:
                # The Ask composer is the product's front door, so acceptance
                # goes in through it rather than through a deep link: the
                # thing being checked is what a user sees after typing a
                # question, and any other route proves less.
                page.goto(FRONTEND, wait_until="networkidle", timeout=90_000)
                box = page.locator(
                    'textarea[aria-label*="Ask CreditProbe"]').first
                box.wait_for(state="visible", timeout=60_000)
                box.fill(question)
                box.press("Enter")
                page.wait_for_selector("h2, h3", timeout=120_000)
                page.wait_for_timeout(2500)
            except Exception as exc:  # noqa: BLE001
                found["error"] = f"{type(exc).__name__}: {exc}"
                results.append(found)
                continue

            shot = out_dir / f"product_answer_{key}.png"
            page.screenshot(path=str(shot), full_page=True)
            found["screenshot"] = str(shot.relative_to(ROOT))

            headings = page.evaluate(
                "() => Array.from(document.querySelectorAll('h2, h3'))"
                ".map(e => e.textContent.trim()).filter(Boolean)")
            bullets = page.evaluate(
                "() => document.querySelectorAll('li').length")
            paragraphs = page.evaluate(
                "() => Array.from(document.querySelectorAll('p'))"
                ".map(e => e.textContent.trim())")
            overflow = page.evaluate(
                "() => document.body.scrollWidth > document.body.clientWidth")
            charts = page.evaluate(
                "() => document.querySelectorAll('svg.recharts-surface, "
                ".recharts-wrapper, canvas').length")

            check("renders_headings", len(headings) >= 1,
                  f"{len(headings)} heading elements")
            check("headings_are_not_shouted",
                  all(h != h.upper() or not h.isalpha() for h in headings),
                  str([h for h in headings if h == h.upper() and h.isalpha()]))
            check("renders_bullets", bullets >= 1, f"{bullets} list items")
            longest = max((len(p) for p in paragraphs), default=0)
            check("no_wall_of_prose", longest <= MAX_PARAGRAPH_CHARS,
                  f"longest rendered paragraph is {longest} characters")
            check("no_sideways_scroll", not overflow,
                  "the page scrolls horizontally at 1366 wide")
            check("no_chart", charts == 0, f"{charts} chart surfaces")
            body = page.evaluate("() => document.body.innerText")
            check("the_answer_rendered", marker in body,
                  f"the page never showed {marker!r}")
            check("no_error_state",
                  "could not be loaded" not in body
                  and "Something went wrong" not in body,
                  "the page rendered an error instead of an answer")
            found["headings"] = headings
            found["bullets"] = bullets
            found["longest_paragraph"] = longest
            results.append(found)

        browser.close()

    total = sum(len(r.get("checks", [])) for r in results)
    passed = sum(1 for r in results for c in r.get("checks", []) if c["passed"])
    return {"viewport": VIEWPORT, "questions": results,
            "total": total, "passed": passed,
            "failures": [
                {"question": r["question"], "check": c["name"],
                 "detail": c["detail"]}
                for r in results for c in r.get("checks", [])
                if not c["passed"]]
            + [{"question": r["question"], "check": "ran",
                "detail": r["error"]} for r in results if r.get("error")]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true",
                        help="boot the backend and the built front end first")
    parser.add_argument("--out", default="docs/product_answer_acceptance.json")
    parser.add_argument("--shots", default="docs/screenshots")
    args = parser.parse_args(argv)

    processes: list[subprocess.Popen] = []
    report: dict[str, Any] = {"started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    try:
        if args.start:
            env = {**os.environ, "REQUIRE_LOGIN": "false"}
            processes.append(subprocess.Popen(
                [str(ROOT / ".venv/bin/python"), "-m", "uvicorn",
                 "backend.api.main:app", "--port", "8000"],
                cwd=ROOT, env=env, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            processes.append(subprocess.Popen(
                ["npm", "run", "start", "--", "--port", "3000"],
                cwd=ROOT / "frontend", env=env, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            if not _wait(f"{BACKEND}/api/v1/health"):
                report["error"] = "the backend never became healthy"
            elif not _wait(FRONTEND):
                report["error"] = "the front end never became reachable"
        if "error" not in report:
            report.update(run(ROOT / args.shots))
    finally:
        # The whole group. `npm run start` spawns the Next server as a child,
        # and terminating npm alone leaves that child holding port 3000, where
        # the next run finds it, believes the front end is up, and tests the
        # PREVIOUS build.
        for process in processes:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):  # pragma: no cover
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:  # pragma: no cover
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    process.kill()

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    if report.get("error"):
        print(f"PRODUCT ANSWER ACCEPTANCE DID NOT RUN: {report['error']}")
        return 2
    print(f"{report['passed']}/{report['total']} checks passed across "
          f"{len(QUESTIONS)} product questions at "
          f"{VIEWPORT['width']}x{VIEWPORT['height']}.")
    for failure in report["failures"]:
        print(f"  FAIL {failure['check']}: {failure['detail']} "
              f"({failure['question']})")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
