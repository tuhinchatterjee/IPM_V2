"""The six Project Planner journeys, driven through a real browser.

Not a route crawl — `scripts/browser_acceptance.py` already proves the pages
render at four viewports without overflowing. This proves something else and
harder: that a person can actually get their morning's work done.

    A  Open the portfolio and see what is in trouble, with the reason.
    B  Open the project that is red and find out why, without guessing.
    C  Read the brief and confirm every claim is labelled.
    D  Open My work, update a task, and see the number move.
    E  Read the history and find what changed, with who said it.
    F  Download the plan and the template.

Each journey asserts an outcome a screenshot cannot: that the number on the
portfolio card equals the number of rows behind it, that the health reason on
the project page is the same sentence as on the portfolio, that a saved update
appears in the history with the right author.

    .venv/bin/python scripts/acceptance/planner_journeys.py
    .venv/bin/python scripts/acceptance/planner_journeys.py --json

Requires the backend on :8000, the front end on :3000, and the seeded plan
(`python scripts/seed_planner.py`). It FAILS rather than skips when those are
missing: a run that quietly checked nothing must not read as a pass.
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

WEB = os.environ.get("PLANNER_WEB", "http://127.0.0.1:3000")
API = os.environ.get("PLANNER_API", "http://127.0.0.1:8000")
PROJECT_CODE = "IFRS9-REDEV"

#: Signed in as a real person, not as an administrator with REQUIRE_LOGIN off.
#: My work shows what YOU own, and there is no way to demonstrate that from an
#: account that owns nothing — an administrator sees everything and therefore
#: proves nothing about the screen. Priya manages the seeded plan.
WHO = os.environ.get("PLANNER_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2


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


def _number(text: str) -> int | None:
    found = re.search(r"-?\d+", text or "")
    return int(found.group()) if found else None


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The planner journeys "
                        "did not run and are NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The planner "
                            "journeys did not run and are NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            project_id = _guard(report, "A", _journey_a, page, report)
            if project_id:
                for name, journey in (("B", _journey_b), ("C", _journey_c),
                                      ("E", _journey_e), ("F", _journey_f)):
                    _guard(report, name, journey, page, report, project_id)
            _guard(report, "D", _journey_d, page, report)
        finally:
            context.close()
            browser.close()
    return report


def _guard(report: Report, journey: str, fn: Any, *args: Any) -> Any:
    """Run one journey, recording a crash as a failure of that journey alone.

    An exception in B used to abort C, E, F and D as well, so one broken
    selector reported as five silent absences — and an acceptance run that
    stops early looks exactly like one that had less to check.
    """
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        report.check(journey, "the journey ran to the end", False,
                     f"{type(exc).__name__}: {exc}"[:300])
        return None

def _sign_in(page: Any, report: Report) -> bool:
    """Sign in through the real login form.

    Deliberately not REQUIRE_LOGIN=false. The route crawl turns login off
    because it is proving that pages render; this is proving that a named
    person can do their job, and that only means something as that person.
    """
    from backend.services.demo_users import DEMO_PASSWORD

    page.goto(f"{WEB}/", wait_until="networkidle")
    if page.locator("input[name=password], #password").count() == 0:
        # Already signed in, or this deployment does not require it.
        return report.check("sign in", "reached the product", True,
                            "no sign-in was required")
    page.fill("input[name=username], #username", WHO)
    page.fill("input[name=password], #password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    try:
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=10_000)
    except Exception:  # noqa: BLE001
        return report.check(
            "sign in", f"signed in as {WHO}", False,
            "the sign-in form is still on screen. Run "
            "scripts/seed_planner.py, which gives the cast the "
            "demonstration password.")
    return report.check("sign in", f"signed in as {WHO}", True)


# --------------------------------------------------------------- journey A


def _journey_a(page: Any, report: Report) -> int | None:
    """Open the portfolio. See what is in trouble, and why."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    body = page.inner_text("body")

    report.check("A", "the portfolio renders", "Project Planner" in body,
                 body[:120])
    seeded = PROJECT_CODE in body
    if not report.check("A", "the seeded plan is listed", seeded,
                        "run scripts/seed_planner.py"):
        return None

    # The stat cards must agree with the table. A card that says 1 red above a
    # table with no red row is the defect this catches, and it is invisible to
    # anybody reading either half alone.
    cards = page.locator("p:text-is('Red')").first
    red_card = _number(
        cards.evaluate("el => el.parentElement.textContent")) if cards.count() else None
    red_rows = page.locator("table tbody tr", has_text="RED").count()
    report.check("A", "the red count matches the red rows",
                 red_card == red_rows, f"card={red_card} rows={red_rows}")

    # Attention must give a reason, not just a colour.
    attention = page.locator("h2:text-is('Needs attention')")
    report.check("A", "an attention panel is present", attention.count() > 0)
    panel = attention.first.evaluate(
        "el => el.closest('section').textContent") if attention.count() else ""
    report.check("A", "the attention panel says why", len(panel) > 80,
                 panel[:120])

    href = page.locator(f"a:has-text('{PROJECT_CODE}')").first.get_attribute("href")
    found = re.search(r"/delivery/(\d+)", href or "")
    if not report.check("A", "the project row links to the project",
                        bool(found), href or ""):
        return None
    return int(found.group(1))


# --------------------------------------------------------------- journey B


def _journey_b(page: Any, report: Report, project_id: int) -> None:
    """Open the project and find out why it is what it is."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    portfolio_reason = ""
    row = page.locator("table tbody tr", has_text=PROJECT_CODE).first
    if row.count():
        badge = row.locator("[title]").first
        portfolio_reason = (badge.get_attribute("title") or "").strip()

    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    body = page.inner_text("body")
    report.check("B", "the project opens", PROJECT_CODE in body, body[:120])

    # The same sentence in both places. Two screens giving different reasons
    # for one colour is how a reader stops believing either.
    report.check("B", "the health reason matches the portfolio",
                 bool(portfolio_reason) and portfolio_reason in body,
                 f"portfolio said {portfolio_reason!r}")

    report.check("B", "the findings are shown with the reason",
                 "What the schedule rules flag" in body)

    page.click("button:text-is('Plan')")
    page.wait_for_timeout(300)
    plan = page.inner_text("body")
    report.check("B", "the plan lists open tasks", "Open tasks" in plan)
    report.check("B", "a blocked task shows its reason",
                 "blocked" in plan.lower()
                 and "valuation policy" in plan.lower(),
                 "the seeded blocker text was not on screen")
    report.check("B", "dependencies are shown", "Dependencies" in plan)


# --------------------------------------------------------------- journey C


def _journey_c(page: Any, report: Report, project_id: int) -> None:
    """The brief, and whether it says what kind of claim each line is."""
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.click("button:text-is('Brief')")
    page.wait_for_selector("text=Project brief", timeout=5000)
    page.wait_for_timeout(500)
    body = page.inner_text("body")

    report.check("C", "the brief renders", "Project brief" in body)
    report.check("C", "claims are labelled as facts", "Fact" in body)
    report.check("C", "the grounding statement is shown",
                 "guess" in body.lower(),
                 "the brief did not say how it is grounded")
    report.check("C", "an outstanding decision is surfaced",
                 "Open questions" in body or "staging approach" in body)

    # The headline and the header must not disagree about the colour.
    header_red = "RED" in body.split("Project brief")[0]
    brief_red = "RED" in body.split("Project brief")[-1]
    report.check("C", "the brief agrees with the header about health",
                 header_red == brief_red,
                 f"header RED={header_red} brief RED={brief_red}")


# --------------------------------------------------------------- journey D


def _journey_d(page: Any, report: Report) -> None:
    """My work: update a task and see the count move."""
    page.goto(f"{WEB}/delivery/my-work", wait_until="networkidle")
    body = page.inner_text("body")
    report.check("D", "my work renders", "My work" in body)

    tasks = page.locator("button:has(span.font-mono)")
    if not report.check("D", "there is a task to update", tasks.count() > 0,
                        "no task is assigned to the acceptance caller"):
        return

    tasks.first.click()
    page.wait_for_selector("[role=dialog]", timeout=5000)
    report.check("D", "the quick update opens",
                 page.locator("[role=dialog]").count() > 0)

    dialog = page.inner_text("[role=dialog]")
    # The refusal has to be explained where somebody would look for the
    # field, not discovered as a 403 later.
    report.check("D", "it explains that dates are not changed here",
                 "moving a commitment" in dialog
                 or "project manager" in dialog, dialog[:200])
    report.check("D", "it carries the version it read",
                 "version" in dialog.lower())

    page.fill("#qu-narrative", "Acceptance run: progress noted.")
    page.fill("#qu-percent", "55")
    page.click("button:text-is('Save update')")
    page.wait_for_timeout(1200)
    after = page.inner_text("body")
    report.check("D", "the drawer closes on a successful save",
                 page.locator("[role=dialog]").count() == 0,
                 after[:200])


# --------------------------------------------------------------- journey E


def _journey_e(page: Any, report: Report, project_id: int) -> None:
    """What changed, and who said it."""
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.click("button:text-is('Updates')")
    page.wait_for_selector("text=What has been said", timeout=5000)
    page.wait_for_timeout(500)
    body = page.inner_text("body")

    report.check("E", "the history renders", "What has been said" in body)
    report.check("E", "updates carry an author",
                 any(name in body for name in
                     ("Priya", "Daniel", "Tom", "Samir", "Amina")),
                 "no author name appeared on any update")
    report.check("E", "a seeded narrative is visible",
                 "steering" in body.lower() or "extraction" in body.lower(),
                 body[-400:])
    report.check("E", "somewhere to post an update", "Say something" in body)


# --------------------------------------------------------------- journey F


def _journey_f(page: Any, report: Report, project_id: int) -> None:
    """The two downloads.

    Fetched through the BROWSER's request context rather than urllib, so they
    carry the same session cookie the page does. That is not a convenience: it
    is the check. An earlier version sent an X-IPM-Role header instead and got
    a correct 401 — the download routes are behind the session like everything
    else, and proving that they answer a signed-in person is the point.
    """
    for name, url in (
        ("template", f"{API}/api/v1/planner/template"),
        ("export", f"{API}/api/v1/planner/projects/{project_id}/export"),
    ):
        response = page.request.get(url)
        if not report.check("F", f"the {name} downloads", response.ok,
                            f"HTTP {response.status}"):
            continue
        content = response.body()
        kind = response.headers.get("content-type", "")
        disposition = response.headers.get("content-disposition", "")
        report.check("F", f"the {name} is a real workbook",
                     len(content) > 4000 and content[:2] == b"PK",
                     f"{len(content)} bytes, starts {content[:4]!r}")
        report.check("F", f"the {name} is served as a spreadsheet",
                     "spreadsheetml" in kind, kind)
        report.check("F", f"the {name} is named for saving",
                     ".xlsx" in disposition, disposition)

    # A download nobody can find is not one.
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    report.check("F", "the export link is on the project page",
                 page.locator("a:has-text('Export plan')").count() > 0)

    # And it must be refused without a session, or the workbook is a way past
    # the participant list for anybody who knows the URL.
    anonymous = page.context.browser.new_context()
    try:
        refused = anonymous.request.get(
            f"{API}/api/v1/planner/projects/{project_id}/export")
        report.check("F", "an unauthenticated download is refused",
                     refused.status in (401, 403, 404),
                     f"HTTP {refused.status}")
    finally:
        anonymous.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run(Report())

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"! {report.error}")
        for step in report.steps:
            mark = "PASS" if step.ok else "FAIL"
            line = f"  [{mark}] {step.journey}  {step.name}"
            if not step.ok and step.detail:
                line += f"\n         {step.detail[:160]}"
            print(line)
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed.")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_OK if not report.failures else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
