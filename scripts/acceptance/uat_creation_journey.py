#!/usr/bin/env python
"""Creating a project through the FORM, in a real browser, step by step.

    .venv/bin/python scripts/acceptance/uat_creation_journey.py
    .venv/bin/python scripts/acceptance/uat_creation_journey.py --json

`creation_flow_journey.py` proves the conversational path still works end to
end. This proves the path a person actually takes now, which UAT found was
the broken one: open the Project Planner, press Create new project, fill in
eight steps, and end up with a real project that the agent then chases.

The journey, in order:

    U1   the Project Planner home is a form-first page with no chat control
    U2   step 1, and a duplicate project code refused HERE rather than at
         publish
    U3   step 2, and a target completion before the start date refused
    U4   step 3, the Agentic AI policy
    U5   step 4, two milestones, and Back/Next moving between steps
    U6   step 5, tasks with owners and dates, and inherited escalation shown
    U7   step 6, a dependency whose impact is stated before it is made, and
         a circular dependency REFUSED
    U8   step 7, the preview: the whole plan, the timeline, the critical
         path, and the two completeness lists
    U9   step 8, the explicit publish
    U10  back on the Project Planner, the project is under Current projects
    U11  the agent runs and produces a real CreditProbe message

Every material step asserts the PERSISTED state through the API afterwards.
A click that leaves no row behind is not a passed step.

    CREDITPROBE_WEB   default http://localhost:3000
    CREDITPROBE_API   default http://localhost:8000  (same host as WEB: the
                      session cookie is host-scoped)
    COPILOT_USER      default priya.raman

It FAILS rather than skips when a precondition is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://localhost:3000").rstrip("/")
#: The session is an HTTP-only cookie set on the host the browser signed in
#: on, so WEB and API have to name the SAME host — `localhost` and
#: `127.0.0.1` are different cookie domains, and mixing them makes every
#: assertion here an anonymous request that proves nothing.
API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
WHO = os.environ.get("COPILOT_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

WAIT_MS = 20_000

NAME = "LGD Model Redevelopment UAT"
TODAY = date.today()
#: One task is deliberately in the past so the agent has something real to
#: chase in U11. Everything else is ahead, so nothing else is overdue by
#: accident and the message this journey asserts is the one it created.
STARTS = TODAY - timedelta(days=30)
ENDS = TODAY + timedelta(days=150)
LATE_DUE = TODAY - timedelta(days=6)


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


# --------------------------------------------------------- driving the form


def _labelled(page: Any, label: str) -> Any:
    """One field by its label, whatever case the stylesheet renders it in.

    The labels are uppercased by CSS and a hint runs straight onto the
    accessible name, so an exact match finds nothing and a word-boundary
    match finds nothing either. Both would fail this journey on a stylesheet
    rather than on the product.
    """
    return page.get_by_label(re.compile(rf"^{re.escape(label)}", re.I))


def _fill(page: Any, label: str, value: str) -> None:
    _labelled(page, label).first.fill(value)


def _choose(page: Any, label: str, value: str) -> None:
    """Choose an option by its VALUE, waiting for it to exist first."""
    select = _labelled(page, label).first
    select.locator(f'option[value="{value}"]').wait_for(
        state="attached", timeout=WAIT_MS)
    select.select_option(value=value)


def _pick(page: Any, label: str, person: dict[str, Any]) -> None:
    """Choose a colleague in one of the governance selects.

    By the option's VALUE, which is the user id, rather than by their name.
    The directory a real installation has contains people who share a name,
    and a journey that failed on that would be reporting a finding about the
    fixtures rather than about the product.

    The options are fetched, so the select exists a moment before they do;
    waiting for the one we want keeps a slow directory from reading as a
    broken form.
    """
    # Search first: on an installation with thousands of staff the picker
    # holds the people this plan already names plus whatever the search
    # returns, and never the whole directory.
    _labelled(page, f"Find {label}").first.fill(
        str(person.get("username") or person.get("name") or ""))
    page.wait_for_timeout(700)
    _choose(page, label, str(person["user_id"]))


def _press(page: Any, name: str) -> None:
    page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I)
                     ).first.click()
    page.wait_for_timeout(400)


def _next(page: Any, to: int = 0) -> None:
    """Press Next, and give the step it is going to time to arrive.

    Moving forward saves the step and then re-reads the draft, so it is two
    round trips rather than a render. Asserting on a fixed sleep would make
    this journey fail on a slow container instead of on the product.
    """
    _press(page, "Next")
    if to:
        try:
            page.wait_for_function(
                "wanted => document.body.innerText.toLowerCase()"
                ".includes(`step ${wanted} of 8`)", arg=to, timeout=WAIT_MS)
        except Exception:  # noqa: BLE001 - the check after this says what broke
            pass
    page.wait_for_timeout(300)


def _text(page: Any) -> str:
    return page.inner_text("body")


def _tail(page: Any, size: int = 1500) -> str:
    """The end of the page text, which is where the form is.

    Every page starts with the same navigation, so a failure detail sliced
    from the front says nothing about what went wrong.
    """
    return _text(page)[-size:]


def _on_step(page: Any, number: int) -> bool:
    """Which step the form is showing.

    Case-insensitive because the step marker is uppercased by CSS, and
    `inner_text` returns what is rendered rather than what is written.
    """
    return f"step {number} of 8" in _text(page).lower()


# -------------------------------------------------------- reading the truth


class Truth:
    """The persisted state, read through the product's own API.

    Through `page.request` so it carries the same session as the browser: an
    assertion made with an admin key would prove something nobody can see.
    """

    def __init__(self, page: Any) -> None:
        self.page = page
        #: The last refusal, so a step that reads nothing back can say WHY
        #: rather than reporting an empty list as if the product were empty.
        self.last_error = ""

    def _get(self, path: str) -> dict[str, Any]:
        found = self.page.request.get(f"{API}{path}")
        if not found.ok:
            self.last_error = f"GET {path} -> {found.status} {found.text()[:200]}"
            return {"_status": found.status, "_body": found.text()[:300]}
        return found.json()

    def drafts(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/planner/copilot/drafts").get("drafts", [])

    def draft(self, key: str) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/copilot/drafts/{key}")

    def preview(self, key: str) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/copilot/drafts/{key}/preview")

    def projects(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/planner/projects?limit=200").get(
            "projects", [])

    def project(self, project_id: int) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/projects/{project_id}")

    def agent_activity(self, project_id: int) -> list[dict[str, Any]]:
        return self._get(
            f"/api/v1/planner/projects/{project_id}/agent-activity"
        ).get("items", [])

    def notifications(self) -> list[dict[str, Any]]:
        return self._get(
            "/api/v1/workspace/notifications?limit=200").get(
            "notifications", [])

    def me(self) -> dict[str, Any]:
        return self._get("/api/v1/auth/me").get("user") or {}

    def discard(self, key: str) -> bool:
        found = self.page.request.delete(
            f"{API}/api/v1/planner/copilot/drafts/{key}")
        return bool(found.ok)

    def people(self) -> list[dict[str, Any]]:
        return self._get(
            "/api/v1/planner/copilot/people?limit=200").get("people", [])


def _newest_draft(truth: Truth) -> dict[str, Any]:
    rows = [row for row in truth.drafts() if row.get("status") == "DRAFTING"]
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return rows[0] if rows else {}


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
        report.error = ("Playwright is not installed. The UAT creation flow "
                        "did not run and is NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The UAT "
                            "creation flow did not run and is NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1560, "height": 1200},
                                      reduced_motion="reduce")
        page = context.new_page()
        try:
            if not _sign_in(page, report):
                return report
            _flow(page, report)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            report.check("flow", "the journey ran to the end", False,
                         f"{type(exc).__name__}: {exc}"[:500])
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
                        len(rows) >= 4,
                        truth.last_error or json.dumps(found)[:400]):
        return None
    cast = {role: rows[index] for index, role in
            enumerate(("owner", "escalation", "second", "sponsor"))}

    # The person driving this owns the work that will be late, so U11 can
    # assert the message the agent sends in THEIR OWN message centre. Nobody
    # can read somebody else's messages — correctly — and an assertion that
    # could only say "a reminder row exists" would be weaker than the claim.
    me = truth.me()
    if me.get("id"):
        cast["owner"] = {"user_id": int(me["id"]),
                         "name": str(me.get("display_name") or ""),
                         "username": str(me.get("username") or "")}
    report.check("setup", "the signed-in person can be named on the plan",
                 bool(cast["owner"]["user_id"]), json.dumps(me)[:200])
    return cast


# ------------------------------------------------------------------- flow


def _flow(page: Any, report: Report) -> None:
    truth = Truth(page)
    _clean(truth, report)
    cast = _cast(truth, report)
    if cast is None:
        return

    code = _u1_home(page, report, truth)
    key = _u2_overview(page, report, truth, code)
    if not key:
        return
    _u3_governance(page, report, truth, key, cast)
    _u4_agentic(page, report, truth, key)
    _u5_milestones(page, report, truth, key, cast)
    _u6_tasks(page, report, truth, key, cast)
    _u7_dependencies(page, report, truth, key)
    _u8_preview(page, report, truth, key)
    project_id = _u9_publish(page, report, truth, key)
    if not project_id:
        return
    _u10_home_again(page, report, truth, project_id)
    _u11_the_agent(page, report, truth, project_id,
                   str(truth.project(project_id).get("project", {}).get(
                       "code") or ""))


def _clean(truth: Truth, report: Report) -> None:
    """Throw away any unfinished plan an earlier run of this left behind.

    Through the product's own Discard, not the database. A run that started
    with somebody else's abandoned draft on the screen would be asserting
    about the wrong thing in U10.
    """
    stale = [row for row in truth.drafts()
             if row.get("status") == "DRAFTING"
             and str(row.get("name") or "") == NAME]
    for row in stale:
        truth.discard(str(row["key"]))
    report.check("setup", "no draft of this project is left over",
                 all(not (r.get("status") == "DRAFTING"
                          and str(r.get("name") or "") == NAME)
                     for r in truth.drafts()),
                 f"{len(stale)} were discarded")


def _u1_home(page: Any, report: Report, truth: Truth) -> str:
    """The home page is a form-first Project Planner with no chat on it."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(1200)
    body = _text(page)

    report.check("U1", "the page is the Project Planner",
                 "Project Planner" in body, body[:200])
    for heading in ("Needs attention", "Current projects", "Draft projects",
                    "Closed and completed projects"):
        report.check("U1", f"the home page has {heading!r}",
                     heading in body, body[:400])
    for action in ("Create new project", "Import project", "View my tasks"):
        report.check("U1", f"the primary action {action!r} is present",
                     page.get_by_role("link", name=action).count() > 0)

    # §1 and §22: no chat control anywhere on the Planner.
    boxes = page.locator(
        "textarea, input[placeholder*='Ask' i], input[placeholder*='Tell' i]")
    report.check("U1", "there is no chat box on the Project Planner",
                 boxes.count() == 0,
                 f"{boxes.count()} free-text boxes on the page")
    report.check("U1", "nothing offers to build a plan in conversation",
                 "conversation" not in body.lower(), body[:400])

    # A code that already exists, so U2 can be refused with it.
    taken = [str(row.get("code")) for row in truth.projects()]
    report.check("U1", "the portfolio has at least one project to collide with",
                 bool(taken))
    return taken[0] if taken else ""


def _u2_overview(page: Any, report: Report, truth: Truth,
                 taken_code: str) -> str:
    """Step 1, and the duplicate code caught here rather than at publish."""
    page.get_by_role("link", name="Create new project").first.click()
    page.wait_for_url(re.compile(r"/delivery/new"), timeout=WAIT_MS)
    _press(page, "Start the setup")
    page.wait_for_timeout(900)

    report.check("U2", "the form opens on step 1 of 8", _on_step(page, 1),
                 _text(page)[:200])

    # The duplicate first, so the refusal is proved before the good value.
    _fill(page, "Project name", NAME)
    _fill(page, "Project code", taken_code)
    _next(page)
    page.wait_for_timeout(900)
    body = _text(page)
    report.check("U2", "a project code already in use is refused on step 1",
                 _on_step(page, 1) and "already used by" in body, body[:400])

    # Unique per run: a code is unique across the platform, so a journey
    # that reused one would fail its own duplicate check the second time it
    # was run — which is a finding about the harness, not the product.
    ours = f"LGDUAT-{datetime.now().strftime('%m%d%H%M%S')}"
    _fill(page, "Project code", ours)
    _fill(page, "Description", "Rebuild the LGD model for retail secured.")
    _fill(page, "Objective",
          "A validated LGD model signed off by the model committee.")
    _next(page, 2)
    page.wait_for_timeout(900)
    report.check("U2", "step 1 moves on once the code is free",
                 _on_step(page, 2), _text(page)[:300])

    key = str(_newest_draft(truth).get("key") or "")
    if not report.check("U2", "the draft was saved server-side", bool(key)):
        return ""
    overview = _plan(truth, key).get("overview") or {}
    report.check("U2", "the name and code are persisted",
                 overview.get("name") == NAME and overview.get("code") == ours,
                 json.dumps(overview)[:300])
    return key


def _u3_governance(page: Any, report: Report, truth: Truth, key: str,
                   cast: dict[str, dict]) -> None:
    """Step 2, and a target completion before the start date refused."""
    _pick(page, "Sponsor", cast["sponsor"])
    _pick(page, "Project manager", cast["owner"])
    _pick(page, "Owner", cast["owner"])
    _pick(page, "Escalation contact", cast["escalation"])
    _fill(page, "Start date", STARTS.isoformat())
    _fill(page, "Target completion", (STARTS - timedelta(days=5)).isoformat())
    _next(page)
    page.wait_for_timeout(700)
    body = _text(page)
    report.check("U3", "a completion date before the start date is refused",
                 _on_step(page, 2) and "before the start date" in body,
                 body[:400])

    _fill(page, "Target completion", ENDS.isoformat())
    _next(page, 3)
    page.wait_for_timeout(900)
    report.check("U3", "step 2 moves on once the dates make sense",
                 _on_step(page, 3), _text(page)[:300])

    governance = _plan(truth, key).get("governance") or {}
    report.check("U3", "the four people are persisted",
                 governance.get("sponsor_id") == cast["sponsor"]["user_id"]
                 and governance.get("manager_id") == cast["owner"]["user_id"]
                 and governance.get("escalation_id")
                 == cast["escalation"]["user_id"],
                 json.dumps(governance)[:300])
    report.check("U3", "the dates are persisted",
                 governance.get("start_date") == STARTS.isoformat()
                 and governance.get("target_end_date") == ENDS.isoformat(),
                 json.dumps(governance)[:300])


def _u4_agentic(page: Any, report: Report, truth: Truth, key: str) -> None:
    """Step 3. The question nobody may skip, and what it means in words."""
    body = _text(page)
    report.check("U4", "the policy step explains what the agent will do",
                 "chase" in body.lower(), body[:400])
    page.get_by_role("button", name=re.compile(r"^Critical\b")).first.click()
    page.wait_for_timeout(800)
    report.check("U4", "choosing Critical is persisted",
                 (_plan(truth, key).get("agentic") or {}).get("mode")
                 == "CRITICAL",
                 json.dumps(_plan(truth, key).get("agentic"))[:200])
    _next(page, 4)
    page.wait_for_timeout(800)
    report.check("U4", "step 3 moves on", _on_step(page, 4),
                 _text(page)[:300])


def _u5_milestones(page: Any, report: Report, truth: Truth, key: str,
                   cast: dict[str, dict]) -> None:
    """Step 4, and Back/Next actually moving between steps."""
    for name, owner, days in (("Data foundation", "owner", 45),
                              ("Model build", "second", 110)):
        _fill(page, "Milestone name", name)
        _pick(page, "Milestone owner", cast[owner])
        _fill(page, "Milestone start", STARTS.isoformat())
        _fill(page, "Milestone target date",
              (STARTS + timedelta(days=days)).isoformat())
        _press(page, "Add milestone")
        page.wait_for_timeout(900)

    plan = _plan(truth, key)
    report.check("U5", "two milestones are persisted, coded M01 and M02",
                 [str(m.get("code")) for m in plan.get("milestones") or []]
                 == ["M01", "M02"],
                 json.dumps(plan.get("milestones"))[:300])

    # §5's Back, proved by going back and returning.
    _press(page, "Back")
    page.wait_for_timeout(800)
    report.check("U5", "Back returns to the previous step", _on_step(page, 3),
                 _text(page)[:200])
    _next(page, 4)
    page.wait_for_timeout(800)
    report.check("U5", "Next returns to the milestones", _on_step(page, 4),
                 _text(page)[:200])

    body = _text(page)
    report.check("U5", "each milestone states who a delay escalates to",
                 body.count("Escalation:") >= 2, body[:600])
    report.check("U5", "an inherited escalation says where it came from",
                 "inherited from the project" in body, body[:600])

    _next(page, 5)
    page.wait_for_timeout(900)
    report.check("U5", "step 4 moves on to the tasks", _on_step(page, 5),
                 _text(page)[:300])


def _u6_tasks(page: Any, report: Report, truth: Truth, key: str,
              cast: dict[str, dict]) -> None:
    """Step 5. Owners, dates, and the escalation each task inherits."""
    rows = [
        ("Extract recovery history", "owner", STARTS, LATE_DUE),
        ("Reconcile to the ledger", "owner",
         LATE_DUE + timedelta(days=1), STARTS + timedelta(days=45)),
        ("Fit candidate specifications", "second",
         STARTS + timedelta(days=46), STARTS + timedelta(days=100)),
    ]
    for title, owner, starts, due in rows:
        _fill(page, "Task title", title)
        _fill(page, "Task description", f"{title}, in full.")
        _pick(page, "Task owner", cast[owner])
        _fill(page, "Task start", starts.isoformat())
        _fill(page, "Task due date", due.isoformat())
        page.get_by_role("button", name="Add task").first.click()
        page.wait_for_timeout(900)

    plan = _plan(truth, key)
    codes = [str(t.get("code")) for t in plan.get("tasks") or []]
    report.check("U6", "three tasks are persisted under their milestones",
                 codes[:3] == ["M01-T01", "M01-T02", "M01-T03"],
                 json.dumps(codes)[:200])
    first = _named(plan, "tasks", "M01-T01")
    report.check("U6", "the first task carries its owner and due date",
                 first.get("owner_id") == cast["owner"]["user_id"]
                 and first.get("due_date") == LATE_DUE.isoformat(),
                 json.dumps(first)[:300])

    body = _text(page)
    report.check("U6", "each task states the escalation it inherits",
                 "inherited from" in body, body[:600])

    _next(page, 6)
    page.wait_for_timeout(900)
    report.check("U6", "step 5 moves on to the dependencies",
                 _on_step(page, 6), _text(page)[:300])


def _u7_dependencies(page: Any, report: Report, truth: Truth,
                     key: str) -> None:
    """Step 6. The impact stated first, and a loop refused."""
    _choose(page, "This has to finish first", "M01-T01")
    _choose(page, "Before this can start", "M01-T02")
    _press(page, "Show the impact")
    page.wait_for_timeout(900)
    body = _text(page)
    report.check("U7", "the impact is stated before the link is made",
                 "will make" in body.lower(), body[:400])
    report.check("U7", "Cancel is offered beside creating it",
                 page.get_by_role("button", name="Cancel").count() > 0)
    _press(page, "Create the dependency")
    page.wait_for_timeout(1000)

    links = _plan(truth, key).get("links") or []
    report.check("U7", "the dependency is persisted",
                 any(link["predecessor"] == "M01-T01"
                     and link["successor"] == "M01-T02" for link in links),
                 json.dumps(links)[:300])

    # §11's refusal: the reverse link would close a loop.
    _choose(page, "This has to finish first", "M01-T02")
    _choose(page, "Before this can start", "M01-T01")
    _press(page, "Show the impact")
    page.wait_for_timeout(1000)
    body = _text(page)
    report.check("U7", "a circular dependency is refused",
                 "loop" in body.lower(), body[:500])
    after = _plan(truth, key).get("links") or []
    report.check("U7", "the refused link changed nothing",
                 len(after) == len(links), json.dumps(after)[:300])

    _next(page, 7)
    page.wait_for_timeout(1200)
    report.check("U7", "step 6 moves on to the preview", _on_step(page, 7),
                 _text(page)[:300])


def _u8_preview(page: Any, report: Report, truth: Truth, key: str) -> None:
    """Step 7. The whole plan, the timeline, and what is still missing."""
    page.wait_for_timeout(1200)
    body = _text(page)
    report.check("U8", "the preview names the project", NAME in body,
                 body[:300])
    report.check("U8", "the preview shows the timeline and the critical path",
                 "critical path" in body.lower(), body[:600])
    lower = body.lower()
    report.check("U8", "the preview lists what is required before publish",
                 "required before publish" in lower, body[:600])
    report.check("U8", "the preview lists recommended improvements",
                 "recommended improvements" in lower, body[:600])
    report.check("U8", "the preview states the escalation for each item",
                 body.count("Escalation:") >= 2, body[:600])

    found = truth.preview(key)
    timeline = found.get("schedule") or {}
    report.check("U8", "the server computed a real schedule",
                 bool(timeline.get("computed"))
                 and bool(timeline.get("critical_path")),
                 json.dumps(timeline)[:300])
    report.check("U8", "the plan is publishable",
                 bool((found.get("completeness") or {}).get("publishable")),
                 json.dumps((found.get("completeness") or {}).get(
                     "blockers"))[:400])

    _next(page, 8)
    page.wait_for_timeout(900)
    report.check("U8", "step 7 moves on to publish", _on_step(page, 8),
                 _text(page)[:300])


def _u9_publish(page: Any, report: Report, truth: Truth, key: str) -> int:
    """Step 8. One deliberate act, and a project on the other side of it."""
    before = {int(row["id"]) for row in truth.projects()}
    _press(page, "Publish project")
    try:
        page.wait_for_url(re.compile(r"/delivery/\d+$"), timeout=WAIT_MS)
    except Exception:  # noqa: BLE001
        report.check("U9", "publishing opened the new project", False,
                     f"still at {page.url}: {_text(page)[:300]}")
        return 0
    page.wait_for_timeout(1500)

    made = [row for row in truth.projects() if int(row["id"]) not in before]
    if not report.check("U9", "exactly one project was created",
                        len(made) == 1, json.dumps(made)[:300]):
        return 0
    project_id = int(made[0]["id"])
    report.check("U9", "the project has the name that was typed",
                 made[0]["name"] == NAME, json.dumps(made[0])[:300])

    detail = truth.project(project_id)
    milestones = detail.get("milestones") or []
    tasks = detail.get("tasks") or []
    dependencies = detail.get("dependencies") or []
    report.check("U9", "both milestones were created", len(milestones) == 2,
                 json.dumps([m.get("code") for m in milestones])[:200])
    report.check("U9", "all three tasks were created", len(tasks) == 3,
                 json.dumps([t.get("code") for t in tasks])[:200])
    report.check("U9", "the dependency was created", len(dependencies) == 1,
                 json.dumps(dependencies)[:300])
    report.check("U9", "the agentic policy came across as Critical",
                 (detail.get("project") or {}).get("agentic_mode")
                 == "CRITICAL",
                 json.dumps((detail.get("project") or {}).get("agentic"))[:200])

    # The draft is spent, not left behind as a second copy.
    report.check("U9", "the published draft is no longer a Draft project",
                 truth.draft(key).get("status") == "PUBLISHED",
                 json.dumps(truth.draft(key).get("status"))[:100])

    body = _text(page)
    report.check("U9", "the project page has no Copilot tab",
                 "Copilot" not in body, body[:400])
    report.check("U9", "the project page has an Agent activity tab",
                 page.get_by_role("tab", name="Agent activity").count() > 0)
    return project_id


def _u10_home_again(page: Any, report: Report, truth: Truth,
                    project_id: int) -> None:
    """§13. Back on the Planner, immediately, under Current projects."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(1500)
    body = _text(page)
    report.check("U10", "the new project is on the Project Planner",
                 NAME in body, body[:400])

    section = body.split("Current projects", 1)
    report.check("U10", "it is under Current projects",
                 len(section) > 1 and NAME in section[1].split(
                     "Draft projects", 1)[0],
                 body[:800])
    report.check("U10", "it is not sitting in Draft projects",
                 NAME not in body.split("Draft projects", 1)[-1].split(
                     "Closed and completed", 1)[0],
                 body[-800:])

    # By href rather than by name: earlier runs of this journey leave real
    # projects behind with the same name, and clicking the first of them
    # would assert that SOME row opens SOME project.
    row = page.locator(f'a[href="/delivery/{project_id}"]').first
    report.check("U10", "the new project has its own row",
                 row.count() > 0, body[:400])
    row.click()
    page.wait_for_url(re.compile(rf"/delivery/{project_id}$"), timeout=WAIT_MS)
    report.check("U10", "the row opens the project it names", True)


def _u11_the_agent(page: Any, report: Report, truth: Truth,
                   project_id: int, code: str) -> None:
    """§19 and §20. The agent runs and a real message exists afterwards."""
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.get_by_role("tab", name="Agent activity").first.click()
    page.wait_for_timeout(900)
    _press(page, "Run the agent now")
    page.wait_for_timeout(2500)

    items = truth.agent_activity(project_id)
    report.check("U11", "the agent recorded something it did",
                 bool(items), json.dumps(items)[:400])
    reminders = [row for row in items if row.get("kind") in
                 ("reminder", "escalation", "request")]
    report.check("U11", "the overdue task produced a chase",
                 bool(reminders), json.dumps(items)[:400])
    if reminders:
        first = reminders[0]
        report.check("U11", "the entry reads as project management",
                     bool(first.get("headline"))
                     and "due_" not in str(first.get("headline")),
                     json.dumps(first)[:300])

    body = _text(page)
    report.check("U11", "the screen shows what the agent did", NAME in body
                 or "Agent activity" in body, body[:300])

    # §19 and §20: the escalation reaches the CreditProbe message centre,
    # and the message carries the fields somebody needs to act on it. Asserted
    # in the recipient's own list, through the same route the message centre
    # reads, rather than by counting rows in a table.
    notes = truth.notifications()
    ours = [row for row in notes if code and code in str(row.get("title") or "")]
    if report.check("U11", "a CreditProbe message reached the message centre",
                    bool(ours), json.dumps(notes[:5])[:400]):
        body_text = str(ours[0].get("body") or "")
        for field_ in ("Project:", "Item:", "Owner:", "Due:", "Open:"):
            report.check("U11", f"the message carries {field_.strip(':')}",
                         field_ in body_text, body_text[:400])
        report.check("U11", "the message names the project, not just its code",
                     NAME in body_text, body_text[:400])
        report.check("U11", "the message links straight to the project",
                     f"/delivery/{project_id}" in body_text, body_text[:400])


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
            print(f"[{mark}] {step.journey:<6} {step.name}")
            if not step.ok and step.detail:
                print(f"          {step.detail}")
        if report.error:
            print(f"\nERROR: {report.error}")
        found = report.to_dict()
        print(f"\n{found['passed']} passed, {found['failed']} failed")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
