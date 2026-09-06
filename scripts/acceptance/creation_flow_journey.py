#!/usr/bin/env python
"""Starting a real project, in a real browser, from the first sentence to the
first reminder.

    .venv/bin/python scripts/acceptance/creation_flow_journey.py
    .venv/bin/python scripts/acceptance/creation_flow_journey.py --json

`copilot_journeys.py` proves the conversation changes the plan on screen.
This proves the thing a client actually buys: that somebody can sit down with
nothing, talk a programme into existence, publish it, find it in the
portfolio afterwards, change it by saying so, and see the agent chase the
person who is late.

The whole flow, in order, as one continuous session:

    M1   start a plan
    M2   name it and say what it is for, in words
    M3   governance: sponsor, manager, owner, escalation contact, dates
    M4   the Agentic AI policy — the question nobody may skip
    M5   the major milestones, in one sentence
    M6   subtasks, milestone by milestone
    M7   owners, dates and an escalation contact
    M8   a dependency made with "Link to previous task"
    M9   a dependency made from the catalogue, with its preview
    M10  a dependency made by saying it
    M11  the completeness check, and clearing what it blocks on
    M12  the preview of the whole plan
    M13  the explicit publish
    M14  it appears in Open Projects
    M15  reopen it, and change it by saying so
    M16  the change is on the project's own record, marked as chat
    M17  the agent sweeps it and chases the person who is late

EVERY material step asserts the PERSISTED state through the API afterwards,
not the pixels that produced it. A journey that only reads the screen proves
the screen; the claim under test is that the database now says what the
person said.

Requires the stack running and the demonstration cast seeded:

    CREDITPROBE_WEB   default http://127.0.0.1:3000
    CREDITPROBE_API   default http://127.0.0.1:8000
    COPILOT_USER      default priya.raman

It FAILS rather than skips when a precondition is missing. "The stack was not
up so we did not check" is the report that lets a broken flow ship.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://127.0.0.1:3000").rstrip("/")
API = os.environ.get("CREDITPROBE_API", "http://127.0.0.1:8000").rstrip("/")
WHO = os.environ.get("COPILOT_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

WAIT_MS = 20_000

#: The project is built in the future on purpose, so that nothing in it is
#: overdue by accident and the one overdue task in M17 is the one this
#: journey made overdue.
TODAY = date.today()
STARTS = TODAY + timedelta(days=7)
ENDS = TODAY + timedelta(days=120)


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

    def check(self, journey: str, name: str, ok: bool,
              detail: str = "") -> bool:
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


# --------------------------------------------------------- driving the page


def _settle(page: Any) -> None:
    try:
        page.wait_for_function(
            "() => !Array.from(document.querySelectorAll('button'))"
            ".some(b => b.textContent.trim() === 'Thinking…')",
            timeout=WAIT_MS)
    except Exception:  # noqa: BLE001 - the assertion after this says what broke
        pass
    page.wait_for_timeout(300)


def _say(page: Any, message: str) -> None:
    box = page.get_by_label("Ask the Project Planner Copilot")
    box.fill(message)
    page.get_by_role("button", name="Send").click()
    page.wait_for_timeout(150)
    _settle(page)


def _go_ahead(page: Any) -> bool:
    button = page.get_by_role("button", name="Go ahead").last
    if button.count() == 0:
        return False
    button.click()
    _settle(page)
    return True


def _confirmed(page: Any, report: Report, journey: str, what: str) -> bool:
    """Press the confirmation, asserting that there was one to press."""
    pressed = _go_ahead(page)
    return report.check(journey, f"{what} was previewed before it happened",
                        pressed, "no confirmation appeared")


def _panel(page: Any) -> str:
    return page.inner_text("body").lower()


# ------------------------------------------------------- reading the truth


class Truth:
    """The persisted state, read back through the product's own API.

    Through `page.request` rather than a fresh client, so it carries the same
    session cookie as the browser: a journey that asserted with an admin key
    would prove something nobody can actually see.
    """

    def __init__(self, page: Any) -> None:
        self.page = page

    def _get(self, path: str) -> dict[str, Any]:
        found = self.page.request.get(f"{API}{path}")
        if not found.ok:
            return {"_status": found.status, "_body": found.text()[:300]}
        return found.json()

    def drafts(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/planner/copilot/drafts").get("drafts", [])

    def draft(self, key: str) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/copilot/drafts/{key}")

    def preview(self, key: str) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/copilot/drafts/{key}/preview")

    def projects(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/planner/projects").get("projects", [])

    def project(self, project_id: int) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/projects/{project_id}")

    def activity(self, project_id: int) -> list[dict[str, Any]]:
        return self._get(
            f"/api/v1/planner/projects/{project_id}/activity").get("items", [])

    def people(self) -> list[dict[str, Any]]:
        return self._get(
            "/api/v1/planner/copilot/people?limit=50").get("people", [])


def _plan(truth: Truth, key: str) -> dict[str, Any]:
    return truth.draft(key).get("plan") or {}


def _named(plan: dict[str, Any], kind: str, code: str) -> dict[str, Any]:
    for row in plan.get(kind) or []:
        if str(row.get("code", "")).upper() == code.upper():
            return row
    return {}


# ------------------------------------------------------------------ runner


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The creation flow did "
                        "not run and is NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The creation "
                            "flow did not run and is NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1560, "height": 1100},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            _flow(page, report)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            report.check("flow", "the journey ran to the end", False,
                         f"{type(exc).__name__}: {exc}"[:400])
        finally:
            context.close()
            browser.close()
    return report


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


def _cast(truth: Truth, report: Report) -> dict[str, dict] | None:
    """Four colleagues to name, read from the product's own directory."""
    found = truth.people()
    rows = [row for row in found
            if len(str(row.get("name") or "").split()) >= 2]
    if not report.check("setup", "there are four colleagues to name",
                        len(rows) >= 4, json.dumps(found)[:300]):
        return None
    roles = ("owner", "escalation", "second", "sponsor")
    return {role: rows[index] for index, role in enumerate(roles)}


def _labelled(page: Any, label: str) -> Any:
    """One field, found by its label whatever case it is rendered in.

    Two things make an exact match wrong here rather than strict. The labels
    are uppercased by CSS, so a case-sensitive match finds nothing; and a
    field with a hint under it has that hint run straight onto its accessible
    name, so "Objective" is really "ObjectiveWhat has to be true for this to
    be finished?" — with no space, which defeats a word-boundary match too.
    Both would fail a journey on a stylesheet rather than on the product, so
    this matches on the label the field's name starts with.
    """
    return page.get_by_label(re.compile(rf"^{re.escape(label)}", re.I))


def _pick(page: Any, label: str, name: str) -> None:
    """Choose a person in one of the governance selects, by their real name."""
    _labelled(page, label).first.select_option(label=name)


def _clear_blockers(page: Any, truth: Truth, key: str,
                    cast: dict[str, dict], rounds: int = 4) -> dict[str, Any]:
    """Say the missing thing until nothing is missing.

    Each blocker names what it wants and what would satisfy it, so this
    answers them in words rather than reaching for the panel: a completeness
    check that can only be cleared through the form would only be half of
    §19. ISO dates on purpose — "25 December" is ambiguous across a year end,
    and a journey that failed on that would be testing the calendar.
    """
    owner = cast["owner"]["name"].split()[0]
    starts = STARTS + timedelta(days=10)
    ends = ENDS - timedelta(days=10)
    detail = truth.draft(key)
    for _ in range(rounds):
        blockers = detail.get("completeness", {}).get("blockers", [])
        if not blockers:
            return detail
        for note in blockers:
            code = str(note.get("code") or "")
            message = str(note.get("message") or "").lower()
            if not code:
                continue
            if "owner" in message:
                _say(page, f"{owner} owns {code}.")
            elif "date" in message and note.get("scope") == "milestone":
                _say(page, f"{code} starts {starts} and ends {ends}.")
            elif "date" in message:
                _say(page, f"{owner} owns {code} until {ends}.")
            else:
                continue
            _go_ahead(page)
        detail = truth.draft(key)
    return detail


# -------------------------------------------------------------- the journey


def _flow(page: Any, report: Report) -> None:  # noqa: PLR0915 - it is a flow
    truth = Truth(page)
    cast = _cast(truth, report)
    if cast is None:
        return

    # ------------------------------------------------------ M1  start a plan
    page.goto(f"{WEB}/delivery/new", wait_until="networkidle")
    before = {row["key"] for row in truth.drafts()}
    page.get_by_role("button", name="Start a plan").click()
    page.wait_for_selector("text=What this project is", timeout=WAIT_MS)
    after = {row["key"] for row in truth.drafts()}
    made = sorted(after - before)
    if not report.check("M1", "a private plan was created and persisted",
                        len(made) == 1, f"{len(made)} new drafts"):
        return
    key = made[0]
    report.check("M1", "it is a draft, not a project",
                 truth.draft(key).get("status") == "DRAFTING",
                 str(truth.draft(key).get("status")))

    # ------------------------------------------- M2  name it, in conversation
    tag = key[-6:].upper()
    name = f"Recovery Rate Refresh {tag}"
    _say(page, f"Call it the {name}.")
    # The objective is typed into the panel rather than said, because §9's
    # claim is that the two surfaces are one document — and the next step
    # reads it back from the same draft the conversation just named.
    _labelled(page, "Objective").fill(
        "A validated set of recovery curves signed off by Model Risk.")
    page.get_by_role("button", name="Save").first.click()
    page.wait_for_timeout(900)
    overview = _plan(truth, key).get("overview") or {}
    report.check("M2", "the name was persisted from what was said",
                 overview.get("name") == name, json.dumps(overview)[:200])
    report.check("M2", "so was the objective",
                 "recovery curves" in str(overview.get("objective", "")),
                 str(overview.get("objective"))[:200])

    # -------------------------------------------------------- M3  governance
    _pick(page, "Sponsor", cast["sponsor"]["name"])
    _pick(page, "Manager", cast["owner"]["name"])
    _pick(page, "Owner", cast["owner"]["name"])
    _pick(page, "Escalation contact", cast["escalation"]["name"])
    _labelled(page, "Starts").first.fill(str(STARTS))
    _labelled(page, "Target completion").first.fill(str(ENDS))
    _labelled(page, "Priority").first.select_option("HIGH")
    page.get_by_role("button", name="Save").nth(1).click()
    page.wait_for_timeout(900)

    governance = _plan(truth, key).get("governance") or {}
    report.check("M3", "the sponsor was persisted",
                 governance.get("sponsor_id") == cast["sponsor"]["user_id"],
                 json.dumps(governance)[:250])
    report.check("M3", "so was the escalation contact",
                 governance.get("escalation_id")
                 == cast["escalation"]["user_id"])
    report.check("M3", "so were the dates and the priority",
                 governance.get("start_date") == str(STARTS)
                 and governance.get("target_end_date") == str(ENDS)
                 and governance.get("priority") == "HIGH",
                 json.dumps(governance)[:250])

    # ------------------------------------------------ M4  the agentic policy
    # By a name that STARTS with Critical: every mode's sentence mentions the
    # critical path, so a loose match would press Standard and pass.
    page.get_by_role("button", name=re.compile(r"^Critical\b")).first.click()
    page.wait_for_timeout(900)
    agentic = _plan(truth, key).get("agentic") or {}
    report.check("M4", "the monitoring policy was chosen and persisted",
                 agentic.get("mode") == "CRITICAL", json.dumps(agentic))
    report.check("M4", "the policy is stated in words before publishing",
                 "escalat" in _panel(page))

    # ------------------------------------------------- M5  major milestones
    _say(page, "Add Data Foundation, Model Build and Independent Validation "
               "as the milestones.")
    plan = _plan(truth, key)
    codes = [str(m.get("code")) for m in plan.get("milestones") or []]
    report.check("M5", "three milestones were created from one sentence",
                 codes == ["M01", "M02", "M03"], str(codes))
    report.check("M5", "each carries the name that was said",
                 [str(m.get("name")) for m in plan["milestones"]]
                 == ["Data Foundation", "Model Build",
                     "Independent Validation"],
                 str([m.get("name") for m in plan.get("milestones") or []]))

    # ------------------------------- M6  subtasks, milestone by milestone
    _say(page, "Under Data Foundation add Data Extraction, Data "
               "Reconciliation and Data Quality Review.")
    _say(page, "Under Model Build add Segmentation and Curve Fitting.")
    _say(page, "Under Independent Validation add Replication and Validation "
               "Report.")
    plan = _plan(truth, key)
    grouped: dict[str, list[str]] = {}
    for task in plan.get("tasks") or []:
        grouped.setdefault(str(task.get("milestone_code")), []).append(
            str(task.get("title")))
    report.check("M6", "every task landed under the milestone it was said "
                       "under",
                 grouped == {
                     "M01": ["Data Extraction", "Data Reconciliation",
                             "Data Quality Review"],
                     "M02": ["Segmentation", "Curve Fitting"],
                     "M03": ["Replication", "Validation Report"]},
                 json.dumps(grouped))
    report.check("M6", "the codes say which milestone they belong to",
                 {str(t.get("code")) for t in plan["tasks"]} == {
                     "M01-T01", "M01-T02", "M01-T03", "M02-T01", "M02-T02",
                     "M03-T01", "M03-T02"},
                 str(sorted(str(t.get("code")) for t in plan["tasks"])))

    # ------------------------------- M7  owners, dates, escalation contacts
    first_due = STARTS + timedelta(days=20)
    _say(page, f"{cast['owner']['name'].split()[0]} owns Data Foundation.")
    _confirmed(page, report, "M7", "the milestone owner")
    _say(page, f"It starts {STARTS.day} {STARTS.strftime('%B')} and ends "
               f"{(STARTS + timedelta(days=45)).day} "
               f"{(STARTS + timedelta(days=45)).strftime('%B')}.")
    _confirmed(page, report, "M7", "the milestone dates")
    _say(page, f"{cast['second']['name'].split()[0]} owns Data Extraction "
               f"until {first_due.day} {first_due.strftime('%B')}.")
    _confirmed(page, report, "M7", "the task owner and due date")
    _say(page, f"{cast['escalation']['name'].split()[0]} is the escalation "
               "owner for Independent Validation.")
    _confirmed(page, report, "M7", "the milestone escalation contact")

    plan = _plan(truth, key)
    foundation = _named(plan, "milestones", "M01")
    extraction = _named(plan, "tasks", "M01-T01")
    validation = _named(plan, "milestones", "M03")
    report.check("M7", "the milestone owner was persisted",
                 foundation.get("owner_id") == cast["owner"]["user_id"],
                 json.dumps(foundation)[:250])
    report.check("M7", "the milestone dates were persisted",
                 foundation.get("start_date") == str(STARTS),
                 json.dumps(foundation)[:250])
    report.check("M7", "the task owner and due date were persisted",
                 extraction.get("owner_id") == cast["second"]["user_id"]
                 and extraction.get("due_date") == str(first_due),
                 json.dumps(extraction)[:250])
    report.check("M7", "the escalation contact was persisted on the "
                       "milestone",
                 validation.get("escalation_id")
                 == cast["escalation"]["user_id"],
                 json.dumps(validation)[:250])

    # --------------------------------------- M8  "link to previous task"
    page.get_by_role("button", name="Link to previous task").nth(1).click()
    page.wait_for_timeout(700)
    report.check("M8", "the link states itself before it exists",
                 "waits for" in _panel(page)
                 or "will wait for" in _panel(page))
    page.get_by_role("button", name="Make the link").first.click()
    page.wait_for_timeout(900)
    links = {(str(row.get("predecessor")), str(row.get("successor")))
             for row in _plan(truth, key).get("links") or []}
    report.check("M8", "the previous-task dependency was persisted",
                 ("M01-T01", "M01-T02") in links, str(sorted(links)))

    # --------------------------------------- M9  from the catalogue, previewed
    _labelled(page, "This has to finish first").first.select_option(
        value="M02-T01")
    _labelled(page, "Before this can start").first.select_option(
        value="M02-T02")
    page.get_by_role("button", name="Show me what that would do").click()
    page.wait_for_timeout(800)
    report.check("M9", "the catalogue link is previewed, not made",
                 ("M02-T01", "M02-T02") not in {
                     (str(r.get("predecessor")), str(r.get("successor")))
                     for r in _plan(truth, key).get("links") or []})
    page.get_by_role("button", name="Make the link").first.click()
    page.wait_for_timeout(900)
    links = {(str(row.get("predecessor")), str(row.get("successor")))
             for row in _plan(truth, key).get("links") or []}
    report.check("M9", "the catalogue dependency was persisted",
                 ("M02-T01", "M02-T02") in links, str(sorted(links)))

    # ------------------------------------------- M10  said, not clicked
    _say(page, "Validation Report can only start after Replication is "
               "finished.")
    _confirmed(page, report, "M10", "the dependency")
    links = {(str(row.get("predecessor")), str(row.get("successor")))
             for row in _plan(truth, key).get("links") or []}
    report.check("M10", "the conversational dependency was persisted",
                 ("M03-T01", "M03-T02") in links, str(sorted(links)))

    # --------------------------------------------- M11  completeness check
    _say(page, "What is still missing?")
    detail = truth.draft(key)
    blockers = detail.get("completeness", {}).get("blockers", [])
    report.check("M11", "the plan reports what it still needs",
                 isinstance(blockers, list))
    report.check("M11", "and it is not publishable while they stand",
                 (not blockers)
                 or detail.get("completeness", {}).get("publishable") is False,
                 json.dumps(detail.get("completeness", {}))[:300])

    # Whatever it blocks on is cleared here, by saying the missing thing —
    # the same way a person would. Publishing past a blocker is not something
    # this journey is allowed to do, so it clears them or it fails.
    detail = _clear_blockers(page, truth, key, cast)
    report.check("M11", "the plan is publishable, with nothing outstanding",
                 detail.get("completeness", {}).get("publishable") is True,
                 json.dumps(detail.get("completeness", {}))[:500])

    # ------------------------------------------------------- M12  preview
    page.get_by_role("button", name="Show me the whole plan").click()
    page.wait_for_timeout(900)
    preview = truth.preview(key)
    totals = preview.get("totals", {})
    report.check("M12", "the preview counts what the plan holds",
                 totals.get("milestones") == 3 and totals.get("tasks") == 7
                 and totals.get("links") == 3, json.dumps(totals))
    screen = _panel(page)
    report.check("M12", "the preview is on screen, in full",
                 "3 milestones" in screen and "7 tasks" in screen,
                 screen[screen.find("publish"):][:200])
    report.check("M12", "every milestone in the preview names who it "
                        "escalates to",
                 all(m.get("escalation", {}).get("source")
                     for m in preview.get("milestones", [])),
                 json.dumps(preview.get("milestones", []))[:300])

    # ------------------------------------------------ M13  explicit publish
    report.check("M13", "nothing exists until the person says so",
                 not any(p.get("name") == name for p in truth.projects()))
    page.get_by_role("button", name="Yes, create this project").click()
    # A NUMBERED url: "/delivery/*" also matches "/delivery/new", which is the
    # page we are still on, so it would return instantly and the journey would
    # then read the project id out of the word "new".
    landed = True
    try:
        page.wait_for_url(re.compile(r"/delivery/\d+$"), timeout=WAIT_MS)
    except Exception:  # noqa: BLE001 - reported below, with what is on screen
        landed = False
    page.wait_for_timeout(1500)

    mine = [row for row in truth.projects() if row.get("name") == name]
    if not report.check("M13", "the project was created",
                        bool(mine), _panel(page)[-600:]):
        return
    project_id = int(mine[0]["id"])
    report.check("M13", "and publishing opened it",
                 landed and page.url.rstrip("/").endswith(str(project_id)),
                 page.url)

    detail = truth.project(project_id)
    project = detail.get("project", {})
    report.check("M13", "the project exists, with the name that was said",
                 project.get("name") == name, json.dumps(project)[:250])
    report.check("M13", "with its milestones",
                 sorted(m["code"] for m in detail.get("milestones", []))
                 == ["M01", "M02", "M03"],
                 str([m.get("code") for m in detail.get("milestones", [])]))
    report.check("M13", "with its tasks, still under their milestones",
                 len(detail.get("tasks", [])) == 7
                 and all(t.get("milestone_id")
                         for t in detail.get("tasks", [])),
                 str(len(detail.get("tasks", []))))
    report.check("M13", "with its dependencies",
                 len(detail.get("dependencies", [])) == 3,
                 str(len(detail.get("dependencies", []))))
    report.check("M13", "and on the monitoring policy that was chosen",
                 project.get("agentic_mode") == "CRITICAL",
                 str(project.get("agentic_mode")))
    report.check("M13", "which the project can state in words",
                 "escalat" in str(
                     (project.get("agentic") or {}).get("sentence", "")),
                 json.dumps(project.get("agentic"))[:250])
    report.check("M13", "the draft is marked published, not left open",
                 truth.draft(key).get("status") == "PUBLISHED")

    # --------------------------------------------- M14  in Open Projects
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(800)
    report.check("M14", "it is listed on the delivery home",
                 name.lower() in _panel(page), name)
    report.check("M14", "and the portfolio API agrees",
                 any(int(p.get("id", 0)) == project_id
                     for p in truth.projects()))

    # ------------------------------- M15  reopen it and change it by saying so
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    # A tab, not a button: the Tabs component sets role="tab", which replaces
    # the implicit button role rather than adding to it.
    page.get_by_role("tab", name="Copilot", exact=True).click()
    page.wait_for_timeout(600)
    _say(page, f"Move M03-T02 to {cast['second']['name'].split()[0]}.")
    report.check("M15", "a change to a running project is previewed first",
                 page.get_by_role("button", name="Go ahead").count() > 0)
    moved_before = [t for t in truth.project(project_id).get("tasks", [])
                    if t["code"] == "M03-T02"]
    report.check("M15", "and nothing has changed yet",
                 bool(moved_before)
                 and (moved_before[0].get("owner") or {}).get("id")
                 != cast["second"]["user_id"])
    _go_ahead(page)
    page.wait_for_timeout(1000)
    moved = [t for t in truth.project(project_id).get("tasks", [])
             if t["code"] == "M03-T02"]
    report.check("M15", "the task really moved, in the database",
                 bool(moved)
                 and (moved[0].get("owner") or {}).get("id")
                 == cast["second"]["user_id"],
                 json.dumps(moved[:1])[:300])

    # ---------------------------------------------- M16  on the record
    history = truth.activity(project_id)
    chat_rows = [row for row in history if row.get("source") == "AI_CHAT"]
    report.check("M16", "the change is on the project's own record",
                 bool(chat_rows), f"{len(history)} entries, none from chat")
    moved_row = [row for row in chat_rows
                 if str(row.get("entity_code")) == "M03-T02"
                 and "owner_id" in (row.get("changes") or {})]
    report.check("M16", "naming the task, the field and who did it",
                 bool(moved_row) and bool(moved_row[0].get("author") or {}),
                 json.dumps(chat_rows[:3])[:400])
    report.check("M16", "and the entry records what it was before",
                 bool(moved_row)
                 and len(moved_row[0]["changes"]["owner_id"]) == 2,
                 json.dumps(moved_row[:1])[:300])

    # ------------------------------------- M17  the agent chases somebody
    # Both dates, in one sentence: a task cannot be due before it starts, and
    # this project was deliberately built in the future so that the only
    # overdue thing in it is the one put there here.
    late_start = TODAY - timedelta(days=30)
    late_due = TODAY - timedelta(days=4)
    _say(page, f"M01-T01 starts {late_start} and ends {late_due}.")
    _go_ahead(page)
    page.wait_for_timeout(800)
    late = [t for t in truth.project(project_id).get("tasks", [])
            if t["code"] == "M01-T01"]
    report.check("M17", "a task was moved into the past to be chased about",
                 bool(late) and str(late[0].get("due_date", "")) < str(TODAY),
                 json.dumps(late[:1])[:250])

    sweep_url = f"{API}/api/v1/planner/projects/{project_id}/sweep"
    swept = page.request.post(sweep_url)
    if report.check("M17", "the manager can run the agent over their own "
                           "project",
                    swept.ok, f"HTTP {swept.status}: {swept.text()[:250]}"):
        sent = swept.json()
        report.check("M17", "and it chased somebody about the late task",
                     int(sent.get("sent", 0)) > 0, json.dumps(sent)[:300])
        report.check("M17", "the reminder is about being overdue",
                     "overdue" in json.dumps(sent.get("by_trigger", {})),
                     json.dumps(sent.get("by_trigger", {})))

        again = page.request.post(sweep_url)
        report.check("M17", "running it again sends nothing new",
                     again.ok and int(again.json().get("sent", 0)) == 0,
                     again.text()[:300])


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
                  + (f" — {step.detail}" if step.detail and not step.ok
                     else ""))
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed")
        if report.error:
            print(f"\n{report.error}")
    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
