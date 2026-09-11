#!/usr/bin/env python
"""Every surface of the Project Planner, looked at rather than reasoned about.

§20, §33, §34, §38, §41, §44 and §45 of the final UAT. The question each
check asks is the one a person asks without knowing they are asking it:

  * **§20** every tab on a project opens, shows something, and does not
    say "undefined", "NaN", "[object Object]" or "Invalid Date";
  * **§41** every control that looks usable IS usable — a button audit
    that presses each enabled button on each tab and watches for an
    uncaught error, a crash, or a screen that empties;
  * **§33** the Timeline draws a timeline rather than a message about one;
  * **§34** My Work shows the signed-in person their own work;
  * **§38** the portfolio can be searched and sorted, and searching for
    something that is not there says so instead of showing everything;
  * **§44** none of it scrolls sideways on a phone;
  * **§45** a project that does not exist gets a sentence, not a stack.

Nothing here asserts a screenshot looks nice. Each check is something a
person would notice and complain about.

    python -m scripts.acceptance.final_uat_surfaces --project 2967
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://localhost:3000").rstrip("/")
API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
SHOTS = Path(os.environ.get(
    "CREDITPROBE_SHOTS",
    "/tmp/claude-0/-home-user-IPM-V2/"
    "5ffce7b7-1bec-5104-89bb-0340b35118dd/scratchpad/shots"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

#: Text that only ever reaches a screen by accident. Each of these is a
#: value that failed to become a sentence somewhere between the database
#: and the page, and every one of them reads to a person as "broken".
LEAKS = ("undefined", "NaN", "[object Object]", "Invalid Date", "null,",
         "Traceback", "TypeError", "Internal Server Error")

#: Buttons that do something a sweep must not do on somebody's project.
#: Everything else on a tab is pressed.
LEAVE_ALONE = ("sign out", "discard", "delete", "remove", "archive", "close "
               "project", "publish", "reset", "unlink", "cancel project")


class Report:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.error = ""
        self.shot_n = 0

    def check(self, what: str, ok: bool, said: str = "") -> bool:
        self.steps.append({"step": what, "ok": bool(ok), "said": said})
        print(f"  {'PASS' if ok else 'FAIL'}  {what}"
              + (f"\n        {said}" if said else ""), flush=True)
        return bool(ok)

    def shot(self, page: Any, name: str) -> None:
        self.shot_n += 1
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"S-{self.shot_n:02d}-{name}.png"))

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if not s["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "error": self.error,
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures)}


def sign_in(page: Any, who: str, secret: str) -> None:
    page.goto(f"{WEB}/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    if page.locator("input[name=password], #password").count():
        page.fill("input[name=username], #username", who)
        page.fill("input[name=password], #password", secret)
        page.click("button[type=submit]")
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=20_000)
        page.wait_for_timeout(1200)


def leaks_in(body: str) -> list[str]:
    """The machine's own vocabulary, showing through onto a person's screen."""
    return [bad for bad in LEAKS if bad in body]


# -------------------------------------------------------- §20, §33 the tabs

def _tabs(report: Report, page: Any, project_id: int) -> None:
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.wait_for_timeout(3000)
    tabs = page.locator("[role=tab]")
    names = [tabs.nth(n).inner_text().strip() for n in range(tabs.count())]
    report.check("the project has tabs to move between", len(names) >= 6,
                 ", ".join(names))

    for name in names:
        tab = page.get_by_role("tab", name=name, exact=True)
        if tab.count() == 0:
            report.check(f"the {name} tab can be opened", False, "not found")
            continue
        tab.first.click()
        page.wait_for_timeout(2200)
        report.shot(page, f"tab-{re.sub(r'[^a-z]+', '-', name.lower())}")
        body = page.inner_text("body")
        report.check(f"the {name} tab shows something",
                     len(body.strip()) > 400, f"{len(body)} characters")
        found = leaks_in(body)
        report.check(f"the {name} tab says nothing a machine wrote",
                     not found, ", ".join(found))
        report.check(f"the {name} tab is not an error page",
                     "something went wrong" not in body.lower()
                     and "unexpected error" not in body.lower())
        if name.lower() == "timeline":
            # §33. A timeline that says "no timeline data" is a message
            # about a timeline, which is not the same thing as one.
            drawn = (page.locator("svg").count() > 0
                     or page.locator("[data-timeline], .recharts-wrapper"
                                     ).count() > 0
                     or bool(re.search(r"M0[12]", body)))
            report.check("the Timeline actually draws the plan", drawn,
                         body[:140].replace("\n", " ⏎ "))


# ---------------------------------------------------------- §41 the buttons

def _buttons(report: Report, page: Any, project_id: int) -> None:
    """Press everything that looks pressable and see what happens."""
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.wait_for_timeout(2500)
    tabs = page.locator("[role=tab]")
    names = [tabs.nth(n).inner_text().strip() for n in range(tabs.count())]

    pressed = 0
    broke: list[str] = []
    for name in names:
        page.get_by_role("tab", name=name, exact=True).first.click()
        page.wait_for_timeout(1800)
        buttons = page.locator("button:not([role=tab])")
        labels: list[str] = []
        for n in range(min(buttons.count(), 40)):
            one = buttons.nth(n)
            try:
                if not one.is_enabled() or not one.is_visible():
                    continue
                label = (one.inner_text() or one.get_attribute("aria-label")
                         or "").strip()
            except Exception:  # noqa: BLE001  — the DOM moved under us
                continue
            if not label or any(skip in label.lower()
                                for skip in LEAVE_ALONE):
                continue
            labels.append(label)
        for label in labels[:18]:
            one = page.get_by_role("button", name=label, exact=True)
            if one.count() == 0:
                continue
            try:
                one.first.click(timeout=4000)
                page.wait_for_timeout(600)
                pressed += 1
            except Exception as exc:  # noqa: BLE001
                broke.append(f"{name}/{label}: {type(exc).__name__}")
                continue
            body = page.inner_text("body")
            if len(body.strip()) < 200:
                broke.append(f"{name}/{label}: the screen emptied")
            found = leaks_in(body)
            if found:
                broke.append(f"{name}/{label}: shows {found[0]!r}")
            # A button that opened something modal has to be closable, or
            # the next press lands on the wrong thing.
            if page.keyboard:
                page.keyboard.press("Escape")
                page.wait_for_timeout(250)
        page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
        page.wait_for_timeout(1600)

    report.check("enough of the project's controls were exercised",
                 pressed >= 15, f"{pressed} button(s) pressed across "
                                f"{len(names)} tab(s)")
    report.check("no control broke the screen it is on", not broke,
                 "; ".join(broke[:6]))


# ------------------------------------------------------------ §34 My Work

def _my_work(report: Report, page: Any, client: Any, who: str) -> None:
    page.goto(f"{WEB}/my-work", wait_until="networkidle")
    page.wait_for_timeout(2500)
    if "404" in page.inner_text("body") or page.url.endswith("/my-work") \
            is False:
        # The route may live under the workspace. Find it by its own link.
        page.goto(f"{WEB}/delivery", wait_until="networkidle")
        page.wait_for_timeout(1500)
        link = page.get_by_role("link", name=re.compile("my work", re.I))
        if link.count():
            link.first.click()
            page.wait_for_timeout(2500)
    report.shot(page, "my-work")
    body = page.inner_text("body")
    report.check("My Work opens", "404" not in body and len(body) > 400,
                 page.url)
    report.check("My Work says nothing a machine wrote",
                 not leaks_in(body), ", ".join(leaks_in(body)))

    mine = client.get(f"{API}/api/v1/planner/my-work", timeout=60)
    report.check("the product knows what this person has to do",
                 mine.status_code == 200, f"HTTP {mine.status_code}")
    if mine.status_code == 200:
        rows = mine.json()
        count = sum(len(v) for v in rows.values() if isinstance(v, list))
        report.check(f"{who} has work listed against their own name",
                     count > 0, json.dumps({k: (len(v) if isinstance(v, list)
                                                else v)
                                            for k, v in rows.items()})[:200])


# ------------------------------------------------- §38 finding a project

def _finding(report: Report, page: Any) -> None:
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(2500)
    box = page.get_by_role("searchbox")
    if box.count() == 0:
        box = page.locator("input[type=search], input[placeholder*='earch']")
    report.check("the portfolio can be searched", box.count() > 0)
    if box.count() == 0:
        return

    before = page.inner_text("body")
    codes = set(re.findall(r"\b[A-Z][A-Z0-9]{2,}-[A-Z0-9-]{2,}\b", before))
    report.check("there is more than one project to search among",
                 len(codes) >= 2, ", ".join(sorted(codes))[:120])

    box.first.fill("Collections")
    page.wait_for_timeout(1800)
    report.shot(page, "search-hit")
    narrowed = page.inner_text("body")
    report.check("searching narrows the list",
                 len(re.findall(r"\b[A-Z][A-Z0-9]{2,}-[A-Z0-9-]{2,}\b",
                                narrowed)) < len(codes)
                 or "collections" in narrowed.lower(),
                 "the list did not change")

    box.first.fill("zzzz-nothing-like-this")
    page.wait_for_timeout(1800)
    report.shot(page, "search-miss")
    empty = page.inner_text("body")
    report.check("searching for something that is not there says so",
                 ("no project" in empty.lower() or "nothing" in empty.lower()
                  or "no match" in empty.lower()),
                 empty[:200].replace("\n", " ⏎ "))
    report.check("and does not fall back to showing everything",
                 len(re.findall(r"\b[A-Z][A-Z0-9]{2,}-[A-Z0-9-]{2,}\b",
                                empty)) < len(codes))
    box.first.fill("")
    page.wait_for_timeout(1500)


# ------------------------------------------------------- §44 on a phone

def _narrow(report: Report, page: Any, project_id: int) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    for where, name in ((f"{WEB}/delivery", "portfolio"),
                        (f"{WEB}/delivery/{project_id}", "project")):
        page.goto(where, wait_until="networkidle")
        page.wait_for_timeout(2500)
        report.shot(page, f"phone-{name}")
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth")
        report.check(f"the {name} does not scroll sideways on a phone",
                    int(overflow) <= 2, f"{overflow}px wider than the screen")
        body = page.inner_text("body")
        report.check(f"the {name} still says what it is at 390px",
                     len(body.strip()) > 300, f"{len(body)} characters")
    page.set_viewport_size({"width": 1440, "height": 1000})


# ------------------------------------------- §45 when something is wrong

def _wrong(report: Report, page: Any, client: Any) -> None:
    page.goto(f"{WEB}/delivery/99999999", wait_until="networkidle")
    page.wait_for_timeout(3000)
    report.shot(page, "missing-project")
    body = page.inner_text("body")
    report.check("a project that does not exist gets a sentence",
                 not leaks_in(body)
                 and ("not found" in body.lower()
                      or "could not" in body.lower()
                      or "cannot" in body.lower()
                      or "no project" in body.lower()),
                 body[:220].replace("\n", " ⏎ "))
    report.check("and not a stack trace",
                 "Traceback" not in body and "at Object." not in body)

    out = client.get(f"{API}/api/v1/planner/projects/99999999", timeout=60)
    report.check("the API says 404 rather than 500",
                 out.status_code == 404, f"HTTP {out.status_code}")
    said = out.json() if out.headers.get("content-type", "").startswith(
        "application/json") else {}
    text = json.dumps(said)
    report.check("and the message is written for a person",
                 "Traceback" not in text and len(text) < 600, text[:200])


# --------------------------------------------------------------- driving

def run(report: Report, *, who: str, project_id: int) -> Report:
    import requests
    from playwright.sync_api import sync_playwright

    from backend.services.demo_users import DEMO_PASSWORD

    client = requests.Session()
    client.post(f"{API}/api/v1/auth/login", timeout=30,
                json={"username": who, "password": DEMO_PASSWORD}
                ).raise_for_status()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME,
                                     args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        sign_in(page, who, DEMO_PASSWORD)

        print("\n§20, §33 — every tab")
        _tabs(report, page, project_id)
        print("\n§41 — every control")
        _buttons(report, page, project_id)
        print("\n§34 — My Work")
        _my_work(report, page, client, who)
        print("\n§38 — finding a project")
        _finding(report, page)
        print("\n§44 — on a phone")
        _narrow(report, page, project_id)
        print("\n§45 — when something is wrong")
        _wrong(report, page, client)

        report.check("the browser reported no uncaught error anywhere",
                     not errors, "; ".join(dict.fromkeys(errors))[:300])
        browser.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default="priya.raman")
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"Every surface, on project {args.project}, as {args.user}")
    report = Report()
    try:
        run(report, who=args.user, project_id=args.project)
    except Exception as exc:  # noqa: BLE001
        report.error = f"{type(exc).__name__}: {exc}"
        print(f"\nstopped: {report.error}")
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2))
    print(f"\n{len(report.steps) - len(report.failures)} of "
          f"{len(report.steps)} checks passed.")
    return 1 if (report.failures or report.error) else 0


if __name__ == "__main__":
    sys.exit(main())
