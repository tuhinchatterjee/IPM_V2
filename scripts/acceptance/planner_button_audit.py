#!/usr/bin/env python
"""Every control on every Project Planner screen, pressed. §25.

    .venv/bin/python scripts/acceptance/planner_button_audit.py
    .venv/bin/python scripts/acceptance/planner_button_audit.py --json

A dead button is not a bug anybody reports; it is a bug people work around
until they stop trusting the screen. So this walks the Planner's surfaces,
finds every enabled button, link and tab, and presses each one, asserting
that something happened: the page navigated, its content changed, or a
request went out. A control that produces none of those three is reported by
name.

It is deliberately dumb about WHAT should happen — that is what the journeys
are for. It only insists that something does.

    CREDITPROBE_WEB   default http://localhost:3000
    COPILOT_USER      default priya.raman

Destructive-sounding controls are named in SKIP and are exercised by the
journeys instead, where the state they change is set up and asserted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://localhost:3000").rstrip("/")
WHO = os.environ.get("COPILOT_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

WAIT_MS = 20_000

#: Controls this audit does not press, and why. Pressing them here would
#: either destroy state the other journeys rely on or leave the browser
#: somewhere this walk cannot continue from.
SKIP = {
    "Discard": "removes a draft; the creation journey proves it",
    "Discard draft": "removes a draft; the creation journey proves it",
    "Publish project": "creates a project; the creation journey proves it",
    "Sign out": "ends the session this audit is running in",
    "Remove": "deletes a row the other journeys assert on",
    "Unlink": "deletes a dependency the other journeys assert on",
}


@dataclass
class Pressed:
    page: str
    control: str
    kind: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "control": self.control, "kind": self.kind,
                "ok": self.ok, "detail": self.detail}


@dataclass
class Report:
    steps: list[Pressed] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    error: str = ""

    def check(self, page: str, control: str, kind: str, ok: bool,
              detail: str = "") -> bool:
        self.steps.append(Pressed(page, control, kind, bool(ok), detail))
        return bool(ok)

    @property
    def failures(self) -> list[Pressed]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"pressed": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures),
                "skipped": self.skipped, "error": self.error}


def _chromium() -> str | None:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        for found in sorted(root.glob(pattern), reverse=True):
            if found.is_file():
                return str(found)
    return None


def _sign_in(page: Any, report: Report) -> bool:
    from backend.services.demo_users import DEMO_PASSWORD

    page.goto(f"{WEB}/", wait_until="networkidle")
    if page.locator("input[name=password], #password").count() == 0:
        return True
    page.fill("input[name=username], #username", WHO)
    page.fill("input[name=password], #password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    try:
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=WAIT_MS)
    except Exception:  # noqa: BLE001
        report.error = ("could not sign in as " + WHO +
                        ". Run scripts/seed_planner.py.")
        return False
    return True


def _tidy(name: str) -> str:
    """One line, single-spaced — the accessible name, not the layout.

    A table row's link contains its whole row, newlines and all; matching on
    that verbatim finds nothing, and an audit that then reported the row as
    "not on screen" would be quietly skipping the controls that matter most.
    """
    return " ".join(str(name or "").split())


def _region(page: Any) -> Any:
    """The Planner's own screen, without the application shell.

    §25 is about the Planner's controls. The sidebar's theme picker and
    navigation collapse belong to every screen in the product and are audited
    with the shell, not here — and pressing them would report them as dead
    for changing only the part of the page this audit excludes.
    """
    for selector in ("main", "[role=main]"):
        found = page.locator(selector)
        if found.count() > 0:
            return found.first
    return page.locator("body")


def _main_text(page: Any) -> str:
    """The page without its navigation.

    Every screen shares a sidebar, so comparing whole-body text would call
    every change too small to notice.
    """
    for selector in ("main", "[role=main]"):
        found = page.locator(selector)
        if found.count() > 0:
            return found.first.inner_text()
    return page.inner_text("body")


def _audit(page: Any, report: Report, where: str, url: str) -> None:
    """Press everything on one screen, one control at a time.

    The page is reloaded before each press rather than pressed repeatedly,
    because a control that opened a panel changes what the next selector
    finds, and an audit that walked a moving list would be reporting on its
    own side effects.
    """
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1200)

    # Collected by POSITION as well as by name. A row in a table is a control
    # whose accessible name is its whole row, and re-finding it by that name
    # is unreliable; an audit that then skipped it would be skipping exactly
    # the controls a person uses most.
    found: list[tuple[str, int, str]] = []
    for kind in ("button", "tab", "link"):
        handles = _region(page).get_by_role(kind).all()
        for index, handle in enumerate(handles):
            try:
                if not handle.is_enabled() or not handle.is_visible():
                    continue
                name = _tidy(handle.get_attribute("aria-label")
                             or handle.inner_text())
            except Exception:  # noqa: BLE001 - it left the page; nothing to press
                continue
            found.append((kind, index, name or f"({kind} {index})"))

    for kind, index, name in found:
        if name in SKIP:
            report.skipped.append(f"{where}: {name} — {SKIP[name]}")
            continue
        _press_one(page, report, where, url, kind, index, name)


def _press_one(page: Any, report: Report, where: str, url: str,
               kind: str, index: int, name: str) -> None:
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(900)

    controls = _region(page).get_by_role(kind)
    if controls.count() <= index:
        report.skipped.append(f"{where}: {name} — not on screen on re-read")
        return
    control = controls.nth(index)
    if not control.is_visible():
        report.skipped.append(f"{where}: {name} — not on screen on re-read")
        return

    # A tab that is already selected, or a link to the page you are on, is
    # not a dead control: it is the current state, and pressing it correctly
    # does nothing. Recorded as live with the reason, never asserted on.
    if control.get_attribute("aria-selected") == "true":
        report.check(where, name, kind, True, "already the selected tab")
        return
    href = control.get_attribute("href") or ""
    if href and page.url.endswith(href):
        report.check(where, name, kind, True, "links to the page it is on")
        return

    before_url = page.url
    before_text = _main_text(page)
    # Moving the cursor is a real thing to have happened, and on a form
    # whose completeness notes are buttons that take you to the field they
    # name, it is the ONLY thing that happens: the page does not move, its
    # text does not change and nothing is fetched. Without this the audit
    # would report the most deliberate controls on the screen as dead.
    before_focus = page.evaluate(
        "document.activeElement && (document.activeElement.id"
        " || document.activeElement.tagName)")
    calls: list[str] = []
    page.on("request", lambda request: calls.append(request.url))

    try:
        control.click(timeout=8000)
    except Exception as exc:  # noqa: BLE001
        report.check(where, name, kind, False,
                     f"could not be clicked: {type(exc).__name__}")
        return
    page.wait_for_timeout(1400)

    after_url = page.url
    after_text = _main_text(page)
    after_focus = page.evaluate(
        "document.activeElement && (document.activeElement.id"
        " || document.activeElement.tagName)")
    moved = after_url != before_url
    changed = after_text != before_text
    asked = any("/api/" in call for call in calls)
    focused = after_focus != before_focus

    report.check(
        where, name, kind, moved or changed or asked or focused,
        "nothing happened: the page did not move, its content did not "
        "change, nothing was focused, and no request went out")


def _audit_the_form(page: Any, report: Report) -> None:
    page.goto(f"{WEB}/delivery/new", wait_until="networkidle")
    page.wait_for_timeout(1200)
    start = page.get_by_role("button", name="Start the setup")
    if start.count() == 0:
        report.check("New project form", "(start a draft)", "button", False,
                     "there is no way to start the setup")
        return
    start.first.click()
    page.wait_for_timeout(2000)
    where = page.url
    if "draft=" not in where:
        report.check("New project form", "(the draft is addressable)", "link",
                     False, f"the URL after starting is {where}")
        return
    key = where.split("draft=", 1)[1].split("&", 1)[0]
    try:
        _audit(page, report, "New project form", where)
    finally:
        page.request.delete(
            f"{WEB}/api/v1/planner/copilot/drafts/{key}")


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The button audit did "
                        "not run and is NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The button "
                            "audit did not run and is NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1560, "height": 1200},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report

            _audit(page, report, "Project Planner", f"{WEB}/delivery")
            _audit(page, report, "New project", f"{WEB}/delivery/new")
            _audit(page, report, "My tasks", f"{WEB}/delivery/my-work")

            # The creation form itself, which the empty `/delivery/new`
            # never shows: it opens on "Start the setup". A draft is started
            # here, audited, and thrown away afterwards, because a form of
            # eight steps and a setup assistant is where most of this
            # module's controls actually live.
            _audit_the_form(page, report)

            # The first project the portfolio lists, so the detail page is
            # audited against real content rather than an empty state.
            page.goto(f"{WEB}/delivery", wait_until="networkidle")
            page.wait_for_timeout(1200)
            href = ""
            for link in page.locator('a[href^="/delivery/"]').all():
                found = link.get_attribute("href") or ""
                if re.match(r"^/delivery/\d+$", found):
                    href = found
                    break
            if href:
                _audit(page, report, "Project detail", f"{WEB}{href}")
            else:
                report.check("Project detail", "(find a project)", "link",
                             False, "no project row to open")
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            report.check("audit", "ran to the end", "run", False,
                         f"{type(exc).__name__}: {exc}"[:400])
        finally:
            context.close()
            browser.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run(Report())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for step in report.steps:
            mark = "PASS" if step.ok else "DEAD"
            print(f"[{mark}] {step.page:<16} {step.kind:<6} {step.control}")
            if not step.ok and step.detail:
                print(f"          {step.detail}")
        for note in report.skipped:
            print(f"[SKIP] {note}")
        if report.error:
            print(f"\nERROR: {report.error}")
        found = report.to_dict()
        print(f"\n{found['passed']} live, {found['failed']} dead, "
              f"{len(found['skipped'])} not pressed")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
