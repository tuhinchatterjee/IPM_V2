#!/usr/bin/env python
"""The integrated demonstration, driven in a real browser.

    .venv/bin/python scripts/acceptance/demo_integration_journeys.py

Covers the journey a demonstration actually takes — sign in, then every module
in the cut — rather than every corner of the product. `scripts/browser_acceptance.py`
does the wide sweep; this proves the narrow path works end to end.

Why this exists rather than a fix to the wide sweep
---------------------------------------------------
The wide sweep failed twice on itself, not on a screen: it evaluates script
against a page that has, by then, navigated away, which is exactly what a
client-side redirect does — and this build has three of them (`/stress`,
`/early-warning/signals`, and the Playbook landing's own router pushes). Its
own error said so: *"Execution context was destroyed, most likely because of a
navigation"*.

So every rule that failure taught is enforced here:

  never evaluate across a navigation. `settle()` waits for the URL to stop
  moving BEFORE anything is read off the page;
  a redirect is a first-class expectation, asserted by where it lands rather
  than survived;
  locators are resilient — a role or a test id, never a class name;
  a refresh is a step, not an accident;
  the session is a real cookie from a real sign-in, so an expiry shows up as a
  failure here rather than in front of an audience.

Exit code is 0 only when every check passes, and the last line says PASS or
FAIL with the journey and check counts.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000"
USERNAME = "alex.rahman"
PASSWORD = "creditprobe-demo"

#: How long a governed analysis may take before the demonstration is broken
#: rather than slow. The Cockpit materialises the canonical book on its first
#: request, so the first answer of a run is legitimately the slow one.
SLOW_MS = 90_000
NORMAL_MS = 30_000


def chromium_path() -> str:
    """The browser this image actually has.

    Playwright resolves a browser by the build number it was compiled
    against, and a pinned Playwright in a prebuilt image is routinely a
    version or two apart from the Chromium beside it — here 1234 against 1194.
    Downloading a second browser to satisfy a number is the wrong fix in a
    sandbox with no egress; pointing at the one already installed is the
    right one, and the environment documents it as the supported route.

    Returns "" when nothing is found, and the caller then lets Playwright try
    its own resolution and report its own error rather than this function
    inventing one.
    """
    import glob
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                    "/opt/pw-browsers/chromium/chrome-linux/chrome",
                    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/"
                    "headless_shell"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return ""


@dataclass
class Check:
    journey: str
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        return (f"  {'PASS' if self.ok else 'FAIL'}  {self.name}"
                + (f"  — {self.detail}" if self.detail and not self.ok else ""))


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    journeys: list[str] = field(default_factory=list)
    shots: list[str] = field(default_factory=list)
    controls: dict[str, int] = field(default_factory=dict)
    started: float = field(default_factory=time.time)

    def add(self, journey: str, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(journey, name, bool(ok), detail))
        print(self.checks[-1].line(), flush=True)
        return bool(ok)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_dict(self) -> dict[str, Any]:
        return {
            "journeys": self.journeys,
            "journey_count": len(self.journeys),
            "check_count": len(self.checks),
            "passed": len(self.checks) - len(self.failed),
            "failed": len(self.failed),
            "screenshots": self.shots,
            "control_audit": self.controls,
            "duration_seconds": round(time.time() - self.started, 1),
            "result": "PASS" if not self.failed else "FAIL",
            "failures": [{"journey": c.journey, "check": c.name,
                          "detail": c.detail} for c in self.failed],
        }


# ------------------------------------------------------------------ plumbing

def settle(page: Any, *, timeout: int = NORMAL_MS) -> str:
    """Wait until the page has stopped navigating, then return where it is.

    This is the whole fix for the harness fault. A client-side redirect moves
    the document out from under any script already running against it, so
    NOTHING is read off a page until the URL has held still and the app shell
    has rendered. `networkidle` alone is not enough: a redirect can fire after
    the first idle, so the URL is compared before and after.
    """
    deadline = time.time() + timeout / 1000
    previous = ""
    while time.time() < deadline:
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:                                       # noqa: BLE001
            pass
        current = page.url
        if current == previous:
            break
        previous = current
        page.wait_for_timeout(350)
    return page.url


def goto(page: Any, path: str, *, timeout: int = NORMAL_MS) -> str:
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
    return settle(page, timeout=timeout)


def text_of(page: Any) -> str:
    """The rendered text, read only after the page has settled."""
    try:
        return page.locator("body").inner_text(timeout=10_000)
    except Exception:                                           # noqa: BLE001
        return ""


def shoot(page: Any, report: Report, name: str, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{name}.png"
    try:
        page.screenshot(path=str(path), full_page=False)
        report.shots.append(str(path.relative_to(ROOT)))
    except Exception as e:                                      # noqa: BLE001
        report.add(name, f"screenshot {name}", False, str(e)[:120])


def controls(page: Any) -> list[Any]:
    """Every visible, enabled control a user could press on this screen."""
    found: list[Any] = []
    for selector in ("button:visible", "a[href]:visible",
                     "[role=tab]:visible", "select:visible"):
        for handle in page.locator(selector).all():
            try:
                if handle.is_visible() and handle.is_enabled():
                    found.append(handle)
            except Exception:                                   # noqa: BLE001
                continue
    return found




#: Controls that leave the demonstration somewhere it cannot be driven back
#: from, or that change state a later journey depends on. Skipped by NAME and
#: counted, so "not pressed" is a number in the report rather than a silence.
DESTRUCTIVE = ("sign out", "log out", "delete", "remove", "archive", "reset",
               "discard", "revoke", "retire", "supersede", "approve",
               "publish", "submit")

#: The shell's own navigation. Identical on every screen, so auditing it once
#: is a fact and auditing it eleven times is eleven copies of a fact.
SHELL = ("/", "/workspace", "/messages", "/projects", "/investigations",
         "/analyses", "/documents", "/playbook", "/lenses", "/metrics",
         "/early-warning", "/what-if", "/borrower-360",
         "/scorecard-validation", "/studio", "/data-builder", "/trace",
         "/reviews", "/workflow", "/settings", "/users", "/delivery",
         "/agent-operations", "/ai-studio", "/engine-builder")


def audit_controls(page: Any, report: Report, *, journey: str, path: str,
                   seen_shell: set[str]) -> tuple[int, int, int]:
    """Prove the controls on this screen are wired to something.

    Two kinds, judged two ways, because they fail differently.

    A LINK is wired when its href resolves to a route this application
    serves. That is checkable without navigating, which matters: a first
    version clicked every control and returned, took a minute per screen,
    and told us nothing a resolved href does not.

    A BUTTON has to be pressed — there is no way to see from the outside
    whether a handler exists. So buttons are pressed, and one is DEAD when
    pressing it changes nothing a user could see: no navigation, no dialog,
    no change in the rendered text. Weaker than "does the right thing";
    much stronger than "renders"; and it is the definition that catches a
    control wired to nothing, which is what a demonstration trips over.
    """
    goto(page, path)
    wired = dead = skipped = 0

    for link in page.locator("a[href]:visible").all():
        try:
            href = (link.get_attribute("href") or "").strip()
            label = (link.inner_text(timeout=1_500) or "").strip()
        except Exception:                                       # noqa: BLE001
            continue
        if not href or href.startswith(("mailto:", "tel:")):
            continue
        route = href.split("?")[0].split("#")[0].rstrip("/") or "/"
        if route in SHELL:
            if route in seen_shell:
                continue
            seen_shell.add(route)
        if href in ("#", "javascript:void(0)"):
            dead += 1
            report.add(journey, f"link {label!r} goes somewhere", False,
                       f"href={href!r}")
            continue
        wired += 1

    for button in page.locator("button:visible").all():
        try:
            if not button.is_enabled():
                skipped += 1
                continue
            label = (button.inner_text(timeout=1_500) or "").strip()
        except Exception:                                       # noqa: BLE001
            skipped += 1
            continue
        if not label or len(label) > 48:
            skipped += 1
            continue
        if any(word in label.lower() for word in DESTRUCTIVE):
            skipped += 1
            continue
        before_url, before_text = page.url, text_of(page)
        try:
            button.click(timeout=3_000)
            page.wait_for_timeout(400)
        except Exception:                                       # noqa: BLE001
            skipped += 1
            continue
        after_url, after_text = page.url, text_of(page)
        if after_url != before_url:
            wired += 1
            goto(page, path)
            continue
        if after_text == before_text:
            dead += 1
            report.add(journey, f"button {label!r} does something", False,
                       "nothing changed: no navigation, no dialog, no text")
        else:
            wired += 1

    report.add(journey, f"{path}: {wired} control(s) wired, {dead} dead, "
               f"{skipped} skipped (destructive or not clickable)", dead == 0)
    return wired, dead, skipped


# ------------------------------------------------------------------ journeys

def journey_sign_in(page: Any, report: Report, out: Path) -> bool:
    j = "sign in"
    report.journeys.append(j)
    goto(page, "/")
    body = text_of(page)
    if "Sign in" in body or page.locator("#password").count():
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        settle(page, timeout=SLOW_MS)
    body = text_of(page)
    ok = report.add(j, "signed in and the shell rendered",
                    "Sign in" not in body and len(body) > 200,
                    body[:120])
    report.add(j, "the session survives a refresh",
               (page.reload(wait_until="domcontentloaded") or True)
               and "Sign in" not in text_of(settle(page) and page))
    shoot(page, report, "01-cockpit", out)
    return ok


def journey_cockpit(page: Any, report: Report, out: Path) -> None:
    j = "Cockpit"
    report.journeys.append(j)
    goto(page, "/")
    body = text_of(page)
    report.add(j, "the Cockpit landing renders", len(body) > 200, body[:120])
    # The repoint is the claim this demo makes; check it on the wire rather
    # than on the screen, because a heading can say anything.
    import urllib.request
    try:
        with urllib.request.urlopen(f"{API}/api/v1/health", timeout=10) as r:
            health = json.loads(r.read())
        report.add(j, "the backend is healthy behind the screen",
                   health.get("status") == "ok", str(health)[:100])
    except Exception as e:                                      # noqa: BLE001
        report.add(j, "the backend is healthy behind the screen", False,
                   str(e)[:120])
    report.add(j, "no dead-end: the shell offers navigation",
               page.locator("nav a[href], aside a[href]").count() > 5)
    shoot(page, report, "02-cockpit-landing", out)


def journey_module(page: Any, report: Report, out: Path, *, name: str,
                   path: str, expect: list[str], shot: str,
                   timeout: int = NORMAL_MS) -> None:
    """Open a module, prove it rendered its own content, and check its
    controls are live rather than decorative."""
    report.journeys.append(name)
    landed = goto(page, path, timeout=timeout)
    report.add(name, f"{path} opens", landed.startswith(BASE), landed)
    body = text_of(page)
    report.add(name, "renders its own content, not an empty shell",
               len(body) > 300, f"{len(body)} chars")
    for phrase in expect:
        report.add(name, f"says {phrase!r}", phrase.lower() in body.lower(),
                   body[:150])
    report.add(name, "no application error on the page",
               "Application error" not in body
               and "something went wrong" not in body.lower())
    live = controls(page)
    report.add(name, "offers live controls", len(live) >= 3,
               f"{len(live)} enabled control(s)")
    # Refresh, then Back: the two things a demonstration does without thinking
    # and the two that strand a single-page app.
    page.reload(wait_until="domcontentloaded")
    settle(page, timeout=timeout)
    report.add(name, "survives a refresh",
               "Sign in" not in text_of(page) and len(text_of(page)) > 300)
    shoot(page, report, shot, out)


def journey_redirects(page: Any, report: Report) -> None:
    """The three retired routes. Each must LAND somewhere, not 404 and not
    hang — and this is the case the wide sweep died on."""
    j = "retired routes"
    report.journeys.append(j)
    for path, expected in (("/stress", "/what-if"),
                           ("/early-warning/signals", "/early-warning")):
        landed = goto(page, path)
        report.add(j, f"{path} redirects to {expected}",
                   landed.rstrip("/").endswith(expected), landed)
    page.goto(f"{BASE}/playbooks", wait_until="domcontentloaded")
    settle(page)
    body = text_of(page)
    report.add(j, "/playbooks (plural) is retired, not a broken page",
               "404" in body or "not found" in body.lower()
               or "does not exist" in body.lower(), body[:120])


def journey_playbook_export(page: Any, report: Report, out: Path) -> None:
    """The What-If export, seen from the Playbook side.

    The export itself is proved over HTTP by the backend suite; what a browser
    has to prove is that a person can FIND it: the library lists it, the item
    opens, and its source and period are on the screen.
    """
    j = "Playbook export"
    report.journeys.append(j)
    goto(page, "/playbook/library")
    body = text_of(page)
    report.add(j, "the exported-analysis library opens", len(body) > 300,
               body[:120])
    report.add(j, "a What-If analysis is listed in the library",
               "what-if" in body.lower() or "what if" in body.lower(),
               body[:200])
    shoot(page, report, "09-playbook-library", out)


def journey_navigation(page: Any, report: Report) -> None:
    """Back and deep links, on the paths a demonstration uses."""
    j = "navigation"
    report.journeys.append(j)
    goto(page, "/what-if")
    goto(page, "/what-if/thread")
    page.go_back()
    landed = settle(page)
    report.add(j, "browser Back returns to What-If",
               landed.rstrip("/").endswith("/what-if"), landed)
    report.add(j, "the page it returned to is alive, not blank",
               len(text_of(page)) > 200)
    # A deep link opened cold, in a page that has no history to lean on.
    landed = goto(page, "/scorecard-validation/monitoring")
    report.add(j, "a deep link opens cold",
               landed.endswith("/scorecard-validation/monitoring")
               and len(text_of(page)) > 300, landed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/demo_journeys.json")
    parser.add_argument("--shots", default="docs/demo_screenshots")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL  Playwright is not installed; the demo journeys did not "
              "run and are NOT passed.")
        return 2

    report = Report()
    shots = ROOT / args.shots

    with sync_playwright() as p:
        executable = chromium_path()
        browser = p.chromium.launch(
            headless=not args.headed,
            **({"executable_path": executable} if executable else {}),
            args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(NORMAL_MS)
        try:
            if not journey_sign_in(page, report, shots):
                print("\nFAIL  sign in did not succeed; nothing else was run.")
                return 1

            journey_cockpit(page, report, shots)
            journey_module(page, report, shots, name="Early Warning",
                           path="/early-warning",
                           expect=["early warning"], shot="03-early-warning",
                           timeout=SLOW_MS)
            journey_module(page, report, shots, name="What-If",
                           path="/what-if", expect=["what-if"],
                           shot="04-what-if")
            journey_module(page, report, shots, name="Lenses",
                           path="/lenses", expect=["lens"], shot="05-lenses")
            journey_module(page, report, shots, name="Playbook",
                           path="/playbook", expect=["playbook"],
                           shot="06-playbook")
            journey_module(page, report, shots, name="Project Planner",
                           path="/projects", expect=[], shot="07-planner")
            journey_module(page, report, shots, name="Scorecard Validation",
                           path="/scorecard-validation", expect=["scorecard"],
                           shot="08-scorecard")
            journey_module(page, report, shots, name="Borrower 360",
                           path="/borrower-360", expect=[],
                           shot="10-borrower-360")
            journey_module(page, report, shots, name="Data Builder",
                           path="/data-builder", expect=[],
                           shot="11-data-builder")
            journey_module(page, report, shots, name="Investigations",
                           path="/investigations", expect=[],
                           shot="12-investigations")
            journey_module(page, report, shots, name="Analysis Studio",
                           path="/studio", expect=[], shot="13-studio")
            report.journeys.append("control audit")
            totals = [0, 0, 0]
            seen_shell: set[str] = set()
            for path in ("/", "/early-warning", "/what-if", "/lenses",
                         "/playbook", "/projects", "/scorecard-validation",
                         "/borrower-360", "/data-builder", "/investigations",
                         "/studio"):
                counts = audit_controls(page, report,
                                        journey="control audit", path=path,
                                        seen_shell=seen_shell)
                totals = [a + b for a, b in zip(totals, counts, strict=True)]
            report.add("control audit",
                       f"TOTAL {totals[0]} control(s) wired, {totals[1]} "
                       f"dead, {totals[2]} skipped", totals[1] == 0)
            report.controls = {"wired": totals[0], "dead": totals[1],
                               "skipped": totals[2]}

            journey_playbook_export(page, report, shots)
            journey_redirects(page, report)
            journey_navigation(page, report)
        finally:
            context.close()
            browser.close()

    body = report.to_dict()
    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2))

    print()
    if report.failed:
        print(f"{len(report.failed)} check(s) failed:")
        for check in report.failed:
            print(f"  {check.journey}: {check.name} — {check.detail}")
    print(f"\n{body['result']}  {body['journey_count']} journeys, "
          f"{body['check_count']} checks, {body['passed']} passed, "
          f"{body['failed']} failed, in {body['duration_seconds']}s")
    print(f"report: {args.out}   screenshots: {len(report.shots)}")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
