#!/usr/bin/env python
"""Building a project by talking to it, driven through a real browser.

    .venv/bin/python scripts/acceptance/copilot_journeys.py
    .venv/bin/python scripts/acceptance/copilot_journeys.py --json

The HTTP tests already prove the reader turns sentences into commands. This
proves the thing they cannot: that a person sitting in front of the product
can type ordinary English into the box on the screen and watch the plan on
the right change — including the part where the Copilot stops and asks, and
the part where it shows what it is about to do and waits.

    G  Start a plan and name it by saying so.
    H  Build it by describing it: a milestone, its owner, its dates, three
       tasks under it, an owner and a due date on one of them.
    I  A dependency, stated before it is made, then made.
    J  One messy paragraph carrying eight facts at once.
    K  Edit what exists: move a task to somebody else, and change how hard
       the agent chases.
    L  The boundary: ask a scorecard question and get sent somewhere else.

Every assertion is made against what is ON SCREEN in the structured panel,
not against the assistant's own reply. A Copilot that convinced itself is
exactly the failure mode this suite exists to catch: §9 says a change made in
chat appears in the panel, and the only way to check that is to read the
panel.

Requires the stack running and the demonstration cast seeded:

    CREDITPROBE_WEB   default http://127.0.0.1:3000
    CREDITPROBE_API   default http://127.0.0.1:8000
    COPILOT_USER      default priya.raman

It FAILS rather than skips when a precondition is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://127.0.0.1:3000").rstrip("/")
API = os.environ.get("CREDITPROBE_API", "http://127.0.0.1:8000").rstrip("/")
WHO = os.environ.get("COPILOT_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

#: Long enough for a slow container, short enough that a hung journey is a
#: failure rather than a stalled run.
WAIT_MS = 15_000


@dataclass
class Step:
    journey: str
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"journey": self.journey, "check": self.name, "ok": self.ok,
                "detail": self.detail}


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    error: str = ""

    def check(self, journey: str, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append(Step(journey, name, bool(ok), detail))
        return bool(ok)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures), "error": self.error}


def _chromium() -> str | None:
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    for pattern in ("chromium-*/chrome-linux/chrome",
                    "chromium_headless_shell-*/chrome-linux/headless_shell"):
        for found in sorted(root.glob(pattern), reverse=True):
            if found.is_file():
                return str(found)
    return None


# ------------------------------------------------------------ the chat box


def _say(page: Any, message: str) -> None:
    """Type into the real input and press the real button."""
    box = page.get_by_label("Ask the Project Planner Copilot")
    box.fill(message)
    page.get_by_role("button", name="Send").click()
    page.wait_for_timeout(150)
    _settle(page)


def _settle(page: Any) -> None:
    """Wait for the turn to come back, however it came back."""
    try:
        page.wait_for_function(
            "() => !Array.from(document.querySelectorAll('button'))"
            ".some(b => b.textContent.trim() === 'Thinking…')",
            timeout=WAIT_MS)
    except Exception:  # noqa: BLE001 - the assertion after this says what broke
        pass
    page.wait_for_timeout(250)


def _confirm(page: Any, report: Report, journey: str, what: str) -> bool:
    """Press "Go ahead" on the preview the Copilot is waiting on.

    Its presence is the assertion: §4 says a change that moves a commitment
    is shown first, so a journey where this button is missing has found the
    preview being skipped.
    """
    button = page.get_by_role("button", name="Go ahead").last
    if not report.check(journey, f"{what} was previewed before it happened",
                        button.count() > 0,
                        "no confirmation appeared"):
        return False
    button.click()
    _settle(page)
    return True


def _panel(page: Any) -> str:
    """Everything on screen, lowercased.

    Lowercased because several labels are uppercased by CSS and `inner_text`
    returns what is rendered: a case-sensitive assertion here reported the
    refusal card as missing when it was on screen saying NOT MY AREA.
    """
    return page.inner_text("body").lower()


def _chat(page: Any) -> str:
    """Only the conversation, lowercased.

    The navigation sidebar names every module in the product, so asserting
    "Scorecard Validation appears somewhere on the page" would pass on a page
    that had refused nothing at all.
    """
    body = page.inner_text("body")
    start = body.find("Tell me what you want to do")
    end = body.find("Draft ", start if start >= 0 else 0)
    return body[start:end if end > start else None].lower()


# ------------------------------------------------------------------ runner


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The Copilot journeys "
                        "did not run and are NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The Copilot "
                            "journeys did not run and are NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1560, "height": 1000},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            people = _people(page, report)
            if people is None:
                return report
            _guard(report, "G", _journey_g, page, report)
            _guard(report, "H", _journey_h, page, report, people)
            _guard(report, "I", _journey_i, page, report)
            _guard(report, "J", _journey_j, page, report, people)
            _guard(report, "K", _journey_k, page, report, people)
            _guard(report, "L", _journey_l, page, report)
        finally:
            context.close()
            browser.close()
    return report


def _guard(report: Report, journey: str, fn: Any, *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        report.check(journey, "the journey ran to the end", False,
                     f"{type(exc).__name__}: {exc}"[:300])
    return None


def _sign_in(page: Any, report: Report) -> bool:
    from backend.services.demo_users import DEMO_PASSWORD

    page.goto(f"{WEB}/", wait_until="networkidle")
    if page.locator("input[name=password], #password").count() == 0:
        return report.check("sign in", "reached the product", True,
                            "no sign-in was required")
    page.fill("input[name=username], #username", WHO)
    page.fill("input[name=password], #password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    try:
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=WAIT_MS)
    except Exception:  # noqa: BLE001
        return report.check(
            "sign in", f"signed in as {WHO}", False,
            "the sign-in form is still on screen. Run scripts/seed_planner.py.")
    return report.check("sign in", f"signed in as {WHO}", True)


def _people(page: Any, report: Report) -> dict[str, str] | None:
    """Two colleagues to name, read from the product's own directory.

    Read rather than hard-coded: a journey that assumed a name would pass on
    a seeded database and fail on a real one for a reason that has nothing to
    do with the Copilot.
    """
    found = page.request.get(f"{API}/api/v1/planner/copilot/people?limit=40")
    if not report.check("setup", "the people directory answered", found.ok,
                        f"HTTP {found.status}"):
        return None
    rows = [row for row in found.json().get("people", [])
            if len(str(row.get("name") or "").split()) >= 2]
    if not report.check("setup", "there are colleagues to name",
                        len(rows) >= 2, f"{len(rows)} found"):
        return None
    # First names, because that is what somebody types.
    return {"owner": rows[0]["name"].split()[0],
            "other": rows[1]["name"].split()[0]}


def _new_plan(page: Any) -> None:
    page.goto(f"{WEB}/delivery/new", wait_until="networkidle")
    start = page.get_by_role("button", name="Start a plan")
    if start.count():
        start.click()
        page.wait_for_selector("text=What this project is", timeout=WAIT_MS)


# ------------------------------------------------------- G — start a plan


def _journey_g(page: Any, report: Report) -> None:
    """The chat is the first thing on the page, and it names the project."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    report.check("G", "the conversation is on the delivery home",
                 page.get_by_label("Ask the Project Planner Copilot").count() > 0)

    _new_plan(page)
    report.check("G", "a plan opens with the conversation beside it",
                 page.get_by_label("Ask the Project Planner Copilot").count() > 0)

    _say(page, "Call it the LGD Model Redevelopment.")
    report.check("G", "the project was named by saying so",
                 "lgd model redevelopment" in _panel(page),
                 _panel(page)[:200])


# --------------------------------------------- H — describe the whole plan


def _journey_h(page: Any, report: Report, people: dict[str, str]) -> None:
    _new_plan(page)
    _say(page, "Call it the Recovery Data Refresh.")

    _say(page, "Add Data Foundation as the first milestone.")
    report.check("H", "the milestone appears in the panel",
                 "data foundation" in _panel(page) and "m01" in _panel(page))

    _say(page, f"{people['owner']} owns Data Foundation.")
    _confirm(page, report, "H", "the owner")
    report.check("H", "the owner is on the milestone",
                 people["owner"].lower() in _panel(page))

    _say(page, "It starts 1 October and ends 31 October.")
    _confirm(page, report, "H", "the dates")
    panel = _panel(page)
    report.check("H", "the dates are on the milestone",
                 "2026-10-01" in panel and "2026-10-31" in panel,
                 panel[:300])

    _say(page, "Under Data Foundation add Data Extraction, Data "
               "Reconciliation and Data Quality Review.")
    panel = _panel(page)
    report.check("H", "three tasks were added from one sentence",
                 all(title in panel for title in
                     ("data extraction", "data reconciliation",
                      "data quality review")))
    report.check("H", "the tasks were coded under their milestone",
                 "m01-t01" in panel and "m01-t03" in panel)

    _say(page, f"{people['owner']} owns Data Extraction until 10 October.")
    _confirm(page, report, "H", "the task owner and due date")
    report.check("H", "the task carries its owner and its date",
                 "2026-10-10" in _panel(page))


# ------------------------------------------------------- I — a dependency


def _journey_i(page: Any, report: Report) -> None:
    _new_plan(page)
    _say(page, "Add Build as the first milestone.")
    _say(page, "Under Build add Data Extraction and Data Reconciliation.")

    _say(page, "Link Data Reconciliation to Data Extraction.")
    said = _panel(page)
    report.check("I", "the link states itself before it exists",
                 "data reconciliation will wait for data extraction" in said,
                 said[:300])
    report.check("I", "nothing is linked yet",
                 "nothing waits for anything yet" in said)

    _confirm(page, report, "I", "the dependency")
    report.check("I", "the dependency is in the plan",
                 "waits for" in _panel(page)
                 and "nothing waits for anything yet" not in _panel(page))


# --------------------------------------------------- J — a messy paragraph


def _journey_j(page: Any, report: Report, people: dict[str, str]) -> None:
    """Eight facts in one turn, three about things it is also creating."""
    _new_plan(page)
    _say(page,
         f"We need a Reporting milestone, {people['owner']} owns it, it "
         "starts 15 November and ends 20 December, and under it add Draft "
         "Report, Committee Review and Final Sign-off. "
         f"{people['other']} owns Draft Report until 30 November. "
         "Committee Review can only start after Draft Report is finished.")
    _confirm(page, report, "J", "the whole paragraph")

    panel = _panel(page)
    for what in ("reporting", "draft report", "committee review",
                 "final sign-off", "2026-11-15", "2026-12-20", "2026-11-30"):
        report.check("J", f"“{what}” reached the plan", what in panel)
    report.check("J", "both owners were resolved",
                 people["owner"].lower() in panel
                 and people["other"].lower() in panel)
    report.check("J", "the dependency between two new tasks was made",
                 "committee review waits for draft report" in panel,
                 panel[:400])


# ------------------------------------------------------ K — editing by chat


def _journey_k(page: Any, report: Report, people: dict[str, str]) -> None:
    _new_plan(page)
    _say(page, "Add Delivery as the first milestone.")
    _say(page, "Under Delivery add Model Review and Handover.")

    _say(page, f"Move Model Review to {people['other']}.")
    _confirm(page, report, "K", "moving a task to somebody else")
    report.check("K", "the task moved",
                 people["other"].lower() in _panel(page))

    _say(page, "Change this project's monitoring to Critical.")
    _confirm(page, report, "K", "changing how hard the agent chases")
    report.check("K", "the monitoring mode changed",
                 "critical" in _panel(page))

    # §10 — a change made in the panel is understood by the next sentence.
    page.get_by_placeholder("Extract recovery history").first.fill(
        "Schema Review")
    page.get_by_role("button", name="Add task").first.click()
    page.wait_for_timeout(600)
    _say(page, f"{people['owner']} owns Schema Review.")
    _confirm(page, report, "K", "an owner on a task the panel created")
    report.check("K", "the conversation understood what the panel added",
                 "schema review" in _panel(page)
                 and people["owner"].lower() in _panel(page))


# --------------------------------------------------------- L — the boundary


def _journey_l(page: Any, report: Report) -> None:
    """A question for another part of the bank, answered with a direction."""
    _new_plan(page)
    _say(page, "What is the gini of the application scorecard?")
    chat = _chat(page)
    report.check("L", "the Copilot refused a scorecard question",
                 "not my area" in chat, chat[:300])
    report.check("L", "it said where the answer lives",
                 "scorecard validation module" in chat)
    report.check("L", "it quoted what stopped it", "stopped at" in chat)

    # And the same words inside the plan's own names are not refused. This is
    # the trap the demo project sets: three of those four words belong to
    # another part of the bank, and a boundary that matched words would
    # refuse to discuss the project it had just created.
    _say(page, "Add Retail Application Scorecard Redevelopment as the first "
               "milestone.")
    report.check("L", "a milestone named after another module is allowed",
                 "retail application scorecard redevelopment" in _panel(page))
    _say(page, "How is the scorecard redevelopment going?")
    report.check("L", "asking about it by name is not refused",
                 _chat(page).count("not my area") == 1,
                 "the second question was refused too")


# ------------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run(Report())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for step in report.steps:
            mark = "PASS" if step.ok else "FAIL"
            print(f"[{mark}] {step.journey}: {step.name}"
                  + (f" — {step.detail}" if step.detail and not step.ok else ""))
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed")
        if report.error:
            print(f"\n{report.error}")
    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
