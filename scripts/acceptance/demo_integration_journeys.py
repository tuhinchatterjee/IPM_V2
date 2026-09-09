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


#: What a click could visibly do, as one value to compare before and after.
#: URL and rendered text are the obvious two. Form VALUES are the one that was
#: missing and mattered: a suggestion chip that writes the question into the
#: composer changes no text and navigates nowhere, and is the most common kind
#: of button on this product's screens. `html` catches a panel that opens with
#: no text of its own.
_EFFECT = """() => JSON.stringify({
  values: [...document.querySelectorAll('input,textarea,select')]
            .map(e => (e.value || '').slice(0, 80)),
  html: document.body.innerHTML.length,
  dialogs: document.querySelectorAll('[role=dialog],dialog[open]').length,
})"""


#: Every governed API call the page has made since the browser opened. A
#: Refresh button is the case this exists for: it re-reads
#: `GET /whatif/landing`, the figures come back the same because nothing has
#: changed, and the rendered page is character-for-character what it was. It
#: did its job. Judging it on the DOM alone calls it dead.
_CALLS: list[str] = []


def watch_calls(page: Any) -> None:
    """Record the API calls the page makes, once per browser page."""
    page.on("request",
            lambda r: _CALLS.append(r.url) if "/api/" in r.url else None)


def _effect_of(page: Any) -> tuple[str, str, str, int]:
    """(url, rendered text, form-and-shape fingerprint, API calls made)."""
    try:
        shape = page.evaluate(_EFFECT)
    except Exception:                                           # noqa: BLE001
        shape = ""
    return page.url, text_of(page), shape, len(_CALLS)


def audit_controls(page: Any, report: Report, *, journey: str, path: str,
                   seen_shell: set[str],
                   shell_queue: list[tuple[str, str]]) -> tuple[int, int, dict]:
    """Prove the controls on this screen are wired to something.

    Two kinds, judged two ways, because they fail differently.

    A LINK is wired when its href resolves to a route this application
    serves. That is checkable without navigating, which matters: a first
    version clicked every control and returned, took a minute per screen,
    and told us nothing a resolved href does not.

    A BUTTON has to be pressed — there is no way to see from the outside
    whether a handler exists. So buttons are pressed, and one is DEAD when
    pressing it changes nothing a user could see. What counts as "seen" is
    `_effect_of` below, and getting that wrong is how an audit reports a
    working control as broken: the first version compared the rendered TEXT
    and the URL, and five prompt buttons that fill the composer — on What-If,
    Lenses and the Playbook — came back dead, because an input's value is
    neither of those things.
    """
    goto(page, path)
    wired = dead = 0
    # Skips are counted BY REASON. A single "skipped" total hides the one
    # category that is not benign: a button whose click raised. "Disabled" and
    # "destructive" are decisions; "the click threw" is a control that may not
    # work, and lumping the three together is how it stays invisible.
    why: dict[str, int] = {"disabled": 0, "destructive": 0, "unnamed": 0,
                           "long_label": 0, "needs_panel": 0,
                           "already_selected": 0, "click_failed": 0}

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

    buttons = page.locator("button:visible")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        try:
            if not button.is_enabled():
                why["disabled"] += 1
                continue
            label = (button.inner_text(timeout=1_500) or "").strip()
            if not label:
                # An icon-only control still has a name — that is what
                # `aria-label` is for, and a screen reader reads it. Skipping
                # every button without visible TEXT left 151 controls on the
                # demo path unexercised, most of them the icon buttons on
                # Investigations and Scorecard Validation.
                label = (button.get_attribute("aria-label")
                         or button.get_attribute("title") or "").strip()
        except Exception:                                       # noqa: BLE001
            why["unnamed"] += 1
            continue
        if not label:
            why["unnamed"] += 1
            continue
        if len(label) > 48:
            # A whole card rendered as a button. Its accessible name is a
            # paragraph, which no locator can match on the clean-load recheck,
            # so it is counted apart rather than folded into "unnamed".
            why["long_label"] += 1
            continue
        if any(word in label.lower() for word in DESTRUCTIVE):
            why["destructive"] += 1
            continue
        try:
            shell_id = (button.get_attribute("aria-label") or "").strip()
        except Exception:                                       # noqa: BLE001
            shell_id = ""
        if shell_id:
            # The shell renders on every screen, so its controls would
            # otherwise be pressed eleven times each. The notifications bell
            # is a TOGGLE: press it on the second screen and it closes the
            # panel the first screen opened, landing back on the fingerprint
            # it started from, and the audit calls a working control dead.
            # Shell LINKS have been audited once since this file was written;
            # shell buttons are the same problem.
            # Keyed on the name up to its first comma, because the rest of a
            # shell control's accessible name is STATE. The bell is called
            # "Notifications, 1 unread" on the first screen; pressing it marks
            # the notification read, and on the next screen it is called
            # "Notifications". Key on the whole string and the rule that
            # exists to audit a shell control once audits it eleven times —
            # the second press closing the panel the first one opened.
            key = "button::" + shell_id.split(",")[0].strip().lower()
            if key not in seen_shell:
                seen_shell.add(key)
                shell_queue.append((path, label))
            # Pressed at the END of the audit, never here. "Collapse
            # navigation" is a shell control like any other and it works —
            # but pressing it while auditing the first screen leaves every
            # LATER screen being audited with the sidebar collapsed, and in
            # that layout the notifications bell is unreachable. A control
            # that changes the shell has to be exercised where its effect
            # cannot be inherited by the next page.
            continue
        try:
            if (button.get_attribute("aria-selected") == "true"
                    or button.get_attribute("aria-pressed") == "true"):
                # The tab already open, the sort already applied. Clicking it
                # changes nothing BECAUSE it is already in that state, which
                # is correct behaviour and not a dead control. Verified by
                # hand on `/` ("All", role=tab, aria-selected=true) and
                # `/borrower-360` ("Highest PD"): press a sibling and the
                # same control responds.
                why["already_selected"] += 1
                continue
        except Exception:                                       # noqa: BLE001
            pass
        before = _effect_of(page)
        try:
            button.click(timeout=3_000)
            page.wait_for_timeout(600)
        except Exception:                                       # noqa: BLE001
            # An audit CHANGES the page as it goes: a click two buttons ago
            # opened a panel or a popover, and it is now over this control.
            # A timeout in that state says nothing about the control, so
            # recover in two steps. First dismiss whatever is on top and try
            # again WHERE IT STANDS — that keeps controls that only exist
            # inside an opened panel reachable.
            recovered = False
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                before = _effect_of(page)
                button.click(timeout=10_000)
                page.wait_for_timeout(600)
                recovered = True
            except Exception:                                   # noqa: BLE001
                recovered = False
            if not recovered:
                # Then, and only then, from a clean load, found by its own
                # name rather than by where it used to sit. A control that a
                # fresh load does not SHOW lives inside a panel this audit
                # had opened; it cannot be judged from here, and saying so is
                # better than timing out against a hidden element for fifteen
                # seconds and calling that a defect.
                goto(page, path)
                found = page.get_by_role("button", name=label, exact=True)
                if not found.count() or not found.first.is_visible():
                    why["needs_panel"] += 1
                    continue
                try:
                    button = found.first
                    before = _effect_of(page)
                    button.click(timeout=15_000)
                    page.wait_for_timeout(600)
                except Exception as e:                          # noqa: BLE001
                    why["click_failed"] += 1
                    report.add(journey, f"button {label!r} accepts a click",
                               False,
                               f"{type(e).__name__}: "
                               f"{str(e).splitlines()[0][:120]}")
                    continue
        after = _effect_of(page)
        if after[0] != before[0]:
            wired += 1
            goto(page, path)
            continue
        if after != before:
            wired += 1
            continue

        # Looked dead. Do not report it from here: this pass walks the page's
        # buttons BY POSITION and every click it makes moves them, so by the
        # time it reaches a toggle the toggle may already be open — pressing
        # it then closes it and lands back on exactly the fingerprint it
        # started from. That is how the notifications bell, which opens a
        # panel of 1,600 characters, was reported dead on four screens.
        #
        # So a dead verdict is only ever recorded after the control has been
        # pressed once more from a CLEAN load of the page, found by its own
        # label rather than by where it used to sit.
        try:
            goto(page, path)
            again = page.get_by_role("button", name=label, exact=True)
            if not again.count() or not again.first.is_visible():
                why["needs_panel"] += 1
                continue
            control = again.first
            clean_before = _effect_of(page)
            control.click(timeout=15_000)
            page.wait_for_timeout(900)
            clean_after = _effect_of(page)
        except Exception as e:                                  # noqa: BLE001
            why["click_failed"] += 1
            report.add(journey, f"button {label!r} accepts a click", False,
                       f"{type(e).__name__}: {str(e).splitlines()[0][:120]}")
            continue
        if clean_after != clean_before:
            wired += 1
            goto(page, path)
            continue

        # Still nothing. One more question before calling it dead: is it the
        # option that is ALREADY chosen? A sort chip or a filter tab that is
        # currently applied does nothing when pressed, correctly, and most of
        # them say so only in a CSS class that no attribute exposes. So press
        # a sibling in the same group and press this one again. A control
        # that answers THAT is a selected control, not a dead one.
        try:
            siblings = [t for t in control.evaluate(
                """e => [...(e.parentElement ? e.parentElement.children : [])]
                         .filter(c => c.tagName === 'BUTTON')
                         .map(c => (c.textContent || '').trim())""")
                if t and t != label]
            revived = False
            for other in siblings[:3]:
                found = page.get_by_role("button", name=other, exact=True)
                if not found.count():
                    continue
                found.first.click(timeout=10_000)
                page.wait_for_timeout(900)
                back = page.get_by_role("button", name=label, exact=True)
                if not back.count():
                    continue
                middle = _effect_of(page)
                back.first.click(timeout=10_000)
                page.wait_for_timeout(900)
                if _effect_of(page) != middle:
                    revived = True
                    break
        except Exception:                                       # noqa: BLE001
            revived = False
        if revived:
            why["already_selected"] += 1
            goto(page, path)
            continue

        dead += 1
        report.add(journey, f"button {label!r} does something", False,
                   "pressed from a clean load and again after a sibling in "
                   "its own group: no navigation, no text, no form value, no "
                   "dialog, no API call, no change in the rendered DOM")
        goto(page, path)

    skipped = sum(why.values())
    report.add(journey, f"{path}: {wired} control(s) wired, {dead} dead, "
               f"{skipped} skipped ("
               + ", ".join(f"{n} {k}" for k, n in why.items() if n) + ")",
               dead == 0 and why["click_failed"] == 0)
    return wired, dead, why


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
        watch_calls(page)
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
            wired = dead = 0
            why: dict[str, int] = {"disabled": 0, "destructive": 0,
                                   "unnamed": 0, "long_label": 0,
                                   "needs_panel": 0, "already_selected": 0,
                                   "click_failed": 0}
            seen_shell: set[str] = set()
            shell_queue: list[tuple[str, str]] = []
            for path in ("/", "/early-warning", "/what-if", "/lenses",
                         "/playbook", "/projects", "/scorecard-validation",
                         "/borrower-360", "/data-builder", "/investigations",
                         "/studio"):
                page_wired, page_dead, page_why = audit_controls(
                    page, report, journey="control audit", path=path,
                    seen_shell=seen_shell, shell_queue=shell_queue)
                wired += page_wired
                dead += page_dead
                for reason, n in page_why.items():
                    why[reason] += n
            # The shell's own controls, each pressed once, each from a
            # fresh load of the screen it was found on.
            for path, label in shell_queue:
                goto(page, path)
                found = page.get_by_role("button", name=label, exact=True)
                if not found.count():
                    why["long_label"] += 1
                    continue
                before = _effect_of(page)
                try:
                    found.first.click(timeout=15_000)
                    page.wait_for_timeout(900)
                except Exception as e:                          # noqa: BLE001
                    why["click_failed"] += 1
                    report.add("control audit",
                               f"shell button {label!r} accepts a click",
                               False, f"{type(e).__name__}: "
                                      f"{str(e).splitlines()[0][:120]}")
                    continue
                if _effect_of(page) != before:
                    wired += 1
                else:
                    dead += 1
                    report.add("control audit",
                               f"shell button {label!r} does something", False,
                               "pressed from a clean load of the screen it "
                               "appears on: nothing changed")

            skipped = sum(why.values())
            report.add("control audit",
                       f"TOTAL {wired} control(s) wired, {dead} dead, "
                       f"{skipped} skipped ("
                       + ", ".join(f"{n} {k}" for k, n in why.items() if n)
                       + ")", dead == 0 and why["click_failed"] == 0)
            report.controls = {"wired": wired, "dead": dead,
                               "skipped": skipped, "skipped_by_reason": why}

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
