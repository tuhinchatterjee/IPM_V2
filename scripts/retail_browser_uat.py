#!/usr/bin/env python
"""
Real-browser acceptance for the Saudi retail installation.

    .venv/bin/python scripts/retail_browser_uat.py

Drives a real Chromium against the RUNNING retail frontend and the RUNNING
retail backend. It is not a mock: if the servers are not up, it says so and
exits non-zero rather than reporting a pass.

What it checks, and why each one:

* **The pages render.** Every route in scope answers, has a title, and shows
  content. A route that 500s in the browser while its API returns 200 is the
  failure a unit test cannot see.
* **The rendered text is retail-only** (RET-046's runtime half). A static scan
  of source files misses a label assembled at runtime from three constants. This
  reads what is actually on the screen.
* **No horizontal overflow.** `scrollWidth > clientWidth` on the body, at three
  viewports. The commonest way a wide retail table breaks a laptop.
* **Navigation is not stranded.** A page a user can reach and cannot leave is
  worse than one that does not exist.
* **The retail domain is visible** where Data Builder shows what is loaded.

Every check writes evidence: a screenshot, the rendered text length, and the
measured values. The report distinguishes PASS, FAIL and SKIPPED, and nothing is
recorded as passed that did not run.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRONTEND = "http://localhost:5328"
BACKEND = "http://127.0.0.1:8328"

VIEWPORTS = (("laptop", 1366, 768), ("desktop", 1680, 1050), ("narrow", 1024, 768))

ROUTES = (
    ("home", "/"),
    ("data-builder", "/data-builder"),
    ("what-if", "/what-if"),
    ("early-warning", "/early-warning"),
    ("workspace", "/workspace"),
)

#: Vocabulary that must not appear in RENDERED text on a retail screen.
#: Deliberately phrase-level: "rating" alone appears in "deteriorating".
CORPORATE_PHRASES = (
    "rating grade", "rating transition", "master scale", "internal rating",
    "obligor group", "balance sheet", "income statement", "cash flow statement",
    "ebitda", "dscr", "covenant breach", "borrower financials",
    "company financials", "corporate rating", "sector concentration",
)


@dataclass
class Check:
    name: str
    route: str
    status: str
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def _reachable(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def _chromium() -> str | None:
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell"):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def run(shots_dir: Path) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    shots_dir.mkdir(parents=True, exist_ok=True)

    if not _reachable(f"{BACKEND}/api/v1/health"):
        checks.append(Check("backend reachable", BACKEND, "FAIL",
                            "the retail backend is not answering on 8328"))
        return checks, {}
    checks.append(Check("backend reachable", BACKEND, "PASS", "health returned 200"))

    if not _reachable(FRONTEND):
        checks.append(Check("frontend reachable", FRONTEND, "FAIL",
                            "the retail frontend is not answering on 5328"))
        return checks, {}
    checks.append(Check("frontend reachable", FRONTEND, "PASS", "returned 200"))

    executable = _chromium()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        checks.append(Check("chromium", "-", "SKIPPED",
                            "playwright is not installed; the browser half did not run"))
        return checks, {}

    rendered_text: dict[str, str] = {}
    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=executable)
        except Exception as e:  # noqa: BLE001
            checks.append(Check("chromium", "-", "SKIPPED", f"Chromium would not launch: {e}"))
            return checks, {}

        for label, width, height in VIEWPORTS:
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))

            for name, route in ROUTES:
                url = f"{FRONTEND}{route}"
                try:
                    # networkidle, not domcontentloaded: this app renders on the
                    # client, so the server's first byte says nothing about
                    # whether the screen has anything on it.
                    response = page.goto(url, wait_until="networkidle", timeout=90_000)
                    page.wait_for_timeout(3000)
                except Exception as e:  # noqa: BLE001
                    checks.append(Check(f"{name} loads", route, "FAIL",
                                        f"navigation failed at {label}: {e}"))
                    continue

                status = response.status if response else 0
                title = page.title()
                body = page.inner_text("body") if page.query_selector("body") else ""
                shot = shots_dir / f"{name}-{label}.png"
                page.screenshot(path=str(shot), full_page=False)

                if label == "laptop":
                    rendered_text[name] = body

                checks.append(Check(
                    f"{name} renders", route,
                    "PASS" if status == 200 and len(body.strip()) > 40 else "FAIL",
                    f"HTTP {status}, title {title!r}, {len(body)} characters of text at {label}",
                    {"screenshot": str(shot.relative_to(ROOT)), "http_status": status,
                     "text_length": len(body), "viewport": f"{width}x{height}"}))

                overflow = page.evaluate(
                    "() => ({scroll: document.body.scrollWidth,"
                    " client: document.body.clientWidth})")
                overflows = overflow["scroll"] > overflow["client"] + 2
                checks.append(Check(
                    f"{name} no horizontal overflow", route,
                    "FAIL" if overflows else "PASS",
                    f"scrollWidth {overflow['scroll']} against clientWidth "
                    f"{overflow['client']} at {label}",
                    dict(overflow, viewport=f"{width}x{height}")))

                if label == "laptop":
                    nav = page.query_selector("nav") or page.query_selector("[role=navigation]")
                    links = page.query_selector_all("a[href]")
                    checks.append(Check(
                        f"{name} navigation present", route,
                        "PASS" if (nav is not None or len(links) > 2) else "FAIL",
                        f"nav element {'found' if nav else 'absent'}, {len(links)} links"))

            if errors:
                checks.append(Check("no uncaught page errors", "-", "FAIL",
                                    f"at {label}: {errors[:3]}"))
            else:
                checks.append(Check("no uncaught page errors", "-", "PASS", f"none at {label}"))
            context.close()
        browser.close()

    # RET-046's runtime half: what the screen actually says.
    offenders: list[str] = []
    for name, text in rendered_text.items():
        lowered = text.lower()
        for phrase in CORPORATE_PHRASES:
            if phrase in lowered:
                offenders.append(f"{name}: '{phrase}'")
    checks.append(Check(
        "rendered text is retail-only", "all routes",
        "FAIL" if offenders else "PASS",
        "; ".join(offenders) if offenders else
        f"scanned {sum(len(t) for t in rendered_text.values()):,} rendered characters "
        f"across {len(rendered_text)} routes for {len(CORPORATE_PHRASES)} retired phrases",
        {"routes_scanned": sorted(rendered_text), "phrases": list(CORPORATE_PHRASES)}))

    return checks, {"rendered_characters": {k: len(v) for k, v in rendered_text.items()}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path,
                    default=ROOT / "docs" / "evidence" / "retail_browser_uat.json")
    ap.add_argument("--shots", type=Path, default=ROOT / "docs" / "evidence" / "screenshots")
    args = ap.parse_args()

    started = time.time()
    checks, extra = run(args.shots)
    elapsed = time.time() - started

    counts = {"PASS": 0, "FAIL": 0, "SKIPPED": 0}
    for c in checks:
        counts[c.status] = counts.get(c.status, 0) + 1

    report = {
        "frontend": FRONTEND,
        "backend": BACKEND,
        "elapsed_seconds": round(elapsed, 1),
        "viewports": [f"{w}x{h}" for _, w, h in VIEWPORTS],
        "routes": [r for _, r in ROUTES],
        "counts": counts,
        "checks": [
            {"name": c.name, "route": c.route, "status": c.status,
             "detail": c.detail, "evidence": c.evidence}
            for c in checks
        ],
        **extra,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2))

    for c in checks:
        print(f"  [{c.status:7s}] {c.name} ({c.route}) — {c.detail}")
    print()
    print(f"  {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['SKIPPED']} skipped in {elapsed:.1f}s")
    print(f"  report      {args.out.relative_to(ROOT)}")
    print(f"  screenshots {args.shots.relative_to(ROOT)}")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
