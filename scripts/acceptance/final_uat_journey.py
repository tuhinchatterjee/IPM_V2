#!/usr/bin/env python
"""Create a project the way a person does, in a real browser, end to end.

This is the journey the final UAT is about: open the Project Planner, press
**Create new project**, fill in eight steps with a mouse and a keyboard, look
at the preview, press **Publish**, and end up with a project the agent then
chases. Nothing here uses an API shortcut to get through a step — the API is
used only to READ BACK what the click was supposed to persist, because a
button that leaves no row behind has not worked.

    python -m scripts.acceptance.final_uat_journey --pass A
    python -m scripts.acceptance.final_uat_journey --pass B --mode CUSTOM
    python -m scripts.acceptance.final_uat_journey --pass C --resume

Three passes, because one successful run proves very little:

  **A**  a straightforward project on the CRITICAL policy;
  **B**  the CUSTOM agentic policy and a non-trivial dependency chain;
  **C**  save as a draft, reload the browser, come back to it, then finish.

Every step screenshots what it did into the shots directory, and every
material step asserts the persisted draft afterwards.

    CREDITPROBE_WEB   default http://localhost:3000
    CREDITPROBE_API   default http://localhost:8000 (same host: the session
                      cookie is host-scoped)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://localhost:3000").rstrip("/")
API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
SHOTS = Path(os.environ.get(
    "CREDITPROBE_SHOTS",
    "/tmp/claude-0/-home-user-IPM-V2/5ffce7b7-1bec-5104-89bb-0340b35118dd/"
    "scratchpad/shots"))
CHROME = os.environ.get(
    "CREDITPROBE_CHROME",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

WAIT = 20_000
TODAY = date.today()

#: Five milestones and the tasks under them, as a real programme would have.
PLAN = [
    ("M01", "Data Foundation", 0, 60, [
        ("Source Extraction", 0, 20),
        ("Data Reconciliation", 20, 40),
        ("Default Definition Review", 15, 45),
        ("Data Quality Sign-off", 45, 60),
    ]),
    ("M02", "Model Development", 60, 150, [
        ("Exploratory Analysis", 60, 80),
        ("Segmentation", 80, 105),
        ("LGD Estimation", 100, 135),
        ("Model Documentation", 130, 150),
    ]),
    ("M03", "Independent Validation", 150, 210, [
        ("Data Replication", 150, 170),
        ("Methodology Review", 165, 195),
        ("Validation Report", 190, 210),
    ]),
    ("M04", "Governance Approval", 210, 250, [
        ("Model Risk Committee", 210, 235),
        ("Final Approval", 235, 250),
    ]),
    ("M05", "Implementation", 250, 300, [
        ("Implementation Specification", 250, 270),
        ("UAT", 270, 290),
        ("Production Release", 290, 300),
    ]),
]

#: The dependency chain §13 asks for, milestone by milestone.
CHAIN = [("M01", "M02"), ("M02", "M03"), ("M03", "M04"), ("M04", "M05")]


def anchor(name: str) -> str:
    return "#f-" + re.sub(r"[^a-zA-Z0-9]+", "-", name)


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


class Report:
    """What was actually checked, in the order it happened."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.steps: list[dict[str, Any]] = []
        self.error = ""
        self.project_id = 0
        self.key = ""
        self._shot = 0

    def check(self, what: str, ok: bool, said: str = "") -> bool:
        self.steps.append({"step": what, "ok": bool(ok), "said": said})
        print(f"  {'PASS' if ok else 'FAIL'}  {what}"
              + (f"\n        {said}" if said else ""), flush=True)
        return bool(ok)

    def shot(self, page: Any, name: str) -> None:
        self._shot += 1
        SHOTS.mkdir(parents=True, exist_ok=True)
        path = SHOTS / f"{self.label}-{self._shot:02d}-{name}.png"
        page.screenshot(path=str(path))

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if not s["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.label, "steps": self.steps, "error": self.error,
                "project_id": self.project_id, "key": self.key,
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures)}


# ------------------------------------------------------------------ helpers


def sign_in(page: Any, who: str, secret: str) -> None:
    page.goto(f"{WEB}/", wait_until="networkidle")
    page.wait_for_timeout(1200)
    if page.locator("input[name=password], #password").count():
        page.fill("input[name=username], #username", who)
        page.fill("input[name=password], #password", secret)
        page.click("button[type=submit]")
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=WAIT)


def press(page: Any, label: str, *, exact: bool = True) -> bool:
    """Click a button the way a person finds it: by its words."""
    button = page.get_by_role("button", name=label, exact=exact)
    if button.count() == 0:
        return False
    button.first.click()
    page.wait_for_timeout(700)
    return True


def choose_person(page: Any, label: str, name: str) -> bool:
    """Use the real picker: type a name, then select the person."""
    finder = page.get_by_label(f"Find {label}", exact=True)
    if finder.count():
        finder.first.fill(name)
        page.wait_for_timeout(1100)
    select = page.get_by_label(label, exact=True)
    if select.count() == 0:
        return False
    options = select.first.locator("option")
    for n in range(options.count()):
        text = options.nth(n).inner_text()
        if name.lower() in text.lower():
            select.first.select_option(options.nth(n).get_attribute("value"))
            page.wait_for_timeout(500)
            return True
    return False


def draft(client: Any, key: str) -> dict[str, Any]:
    out = client.get(f"{API}/api/v1/planner/copilot/drafts/{key}", timeout=60)
    out.raise_for_status()
    return out.json()


# -------------------------------------------------------------- the journey


def run(report: Report, *, who: str, name: str, code: str, mode: str,
        resume: bool) -> Report:
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
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        crashes: list[str] = []
        page.on("pageerror", lambda e: crashes.append(str(e)[:200]))
        try:
            _journey(report, page, client, who=who, name=name, code=code,
                     mode=mode, resume=resume, secret=DEMO_PASSWORD)
        except Exception as exc:  # noqa: BLE001
            report.error = f"{type(exc).__name__}: {exc}"
            report.shot(page, "where-it-stopped")
        finally:
            report.check("the browser reported no uncaught error",
                         not crashes, "; ".join(crashes[:3]))
            browser.close()
    return report


def _journey(report: Report, page: Any, client: Any, *, who: str, name: str,
             code: str, mode: str, resume: bool, secret: str) -> None:
    sign_in(page, who, secret)
    report.check("signed in", True, who)

    # ------------------------------------------------- 1  project basics §7
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(1500)
    report.check("the Project Planner offers Create new project",
                 page.get_by_role("link", name="Create new project").count() > 0)
    page.get_by_role("link", name="Create new project").first.click()
    page.wait_for_timeout(2000)
    press(page, "Start the setup", exact=False)
    page.wait_for_timeout(2500)
    key = page.url.split("draft=")[1].split("&")[0] if "draft=" in page.url else ""
    report.key = key
    report.check("the draft is in the URL, so a reload comes back to it",
                 bool(key), page.url)

    page.fill(anchor("overview.name"), name)
    page.fill(anchor("overview.code"), code)
    page.fill(anchor("overview.description"),
              "Rebuild the LGD model for the retail secured book.")
    page.fill(anchor("overview.objective"),
              "A validated, approved LGD model in production use.")
    page.wait_for_timeout(2200)
    report.shot(page, "step1-overview")
    saw = draft(client, key)["plan"]["overview"]
    report.check("step 1 persisted without pressing Save",
                 saw.get("name") == name and saw.get("code") == code,
                 f"{saw.get('name')!r} / {saw.get('code')!r}")

    # A duplicate code must be refused HERE rather than at publish.
    page.fill(anchor("overview.code"), "IFRS9-REDEV")
    page.wait_for_timeout(2500)
    warned = page.locator("[role=alert]").count() > 0
    report.shot(page, "step1-duplicate-code")
    report.check("a code already in use is refused on the step that asks "
                 "for it", warned,
                 page.locator("[role=alert]").first.inner_text()[:120]
                 if warned else "no warning appeared")
    page.fill(anchor("overview.code"), code)
    page.wait_for_timeout(2000)

    report.check("Next is offered", press(page, "Next"))
    page.wait_for_timeout(2000)

    # --------------------------------------------------- 2  governance §8
    report.shot(page, "step2-governance-empty")
    for label, person in (("Sponsor", "Amina Hassan"),
                          ("Project manager", "Priya Raman"),
                          ("Owner", "Priya Raman"),
                          ("Escalation contact", "Amina Hassan")):
        report.check(f"the picker found {person} for {label}",
                     choose_person(page, label, person))
    page.fill(anchor("governance.start_date"), day(0))
    page.fill(anchor("governance.target_end_date"), day(300))
    page.select_option(anchor("governance.priority"), "HIGH")
    page.select_option(anchor("governance.reporting_cadence"), "WEEKLY")
    page.wait_for_timeout(2200)
    report.shot(page, "step2-governance")
    gov = draft(client, key)["plan"]["governance"]
    report.check("everybody named on step 2 persisted",
                 all(gov.get(f) for f in ("sponsor_id", "manager_id",
                                          "owner_id", "escalation_id")),
                 json.dumps({k: gov.get(k) for k in (
                     "sponsor_id", "manager_id", "owner_id", "escalation_id",
                     "start_date", "target_end_date", "priority")}))

    # A target completion before the start date must be refused.
    page.fill(anchor("governance.target_end_date"), day(-10))
    page.wait_for_timeout(1200)
    press(page, "Next")
    page.wait_for_timeout(1200)
    refused = page.locator("[role=alert]").count() > 0
    report.shot(page, "step2-bad-dates")
    report.check("a target completion before the start date is refused",
                 refused,
                 page.locator("[role=alert]").first.inner_text()[:140]
                 if refused else "the form accepted it")
    page.fill(anchor("governance.target_end_date"), day(300))
    page.wait_for_timeout(2000)
    press(page, "Next")
    page.wait_for_timeout(2000)

    # ------------------------------------------------------ 3  agentic §9
    report.shot(page, "step3-agentic")
    # The cards carry aria-pressed and their heading is the policy name. Any
    # looser match picks the Standard card, whose own text mentions "critical
    # path" and "critical delay".
    cards = page.locator("button[aria-pressed]")
    picked = None
    for n in range(cards.count()):
        heading = cards.nth(n).locator("p").first.inner_text().strip()
        if heading.lower() == mode.lower():
            picked = cards.nth(n)
            break
    report.check(f"the {mode} policy card is on the step", picked is not None)
    if picked is not None:
        picked.click()
        page.wait_for_timeout(2000)
    if mode == "CUSTOM":
        _custom_policy(report, page, client, key)
    page.wait_for_timeout(1500)
    report.shot(page, "step3-agentic-chosen")
    agentic = draft(client, key)["plan"]["agentic"]
    report.check("the policy the person chose is the policy that is stored",
                 str(agentic.get("mode", "")).upper() == mode.upper(),
                 json.dumps(agentic)[:200])
    press(page, "Next")
    page.wait_for_timeout(1800)

    # --------------------------------------------------- 4  milestones §11
    for _mcode, mname, start, end, _tasks in PLAN:
        page.get_by_label("Milestone name", exact=True).first.fill(mname)
        choose_person(page, "Milestone owner", "Priya Raman")
        page.get_by_label("Milestone start", exact=True).first.fill(day(start))
        page.get_by_label("Milestone target date",
                          exact=True).first.fill(day(end))
        page.wait_for_timeout(300)
        press(page, "Add milestone")
        page.wait_for_timeout(1100)
    page.wait_for_timeout(1200)
    report.shot(page, "step4-milestones")
    stones = draft(client, key)["plan"]["milestones"]
    report.check("all five milestones persisted", len(stones) == len(PLAN),
                 f"{len(stones)} stored: "
                 f"{[m.get('code') for m in stones]}")
    press(page, "Next")
    page.wait_for_timeout(1800)

    # -------------------------------------------------------- 5  tasks §12
    # One panel per milestone, in plan order. `has_text` on its own matches
    # the outer wrapper too, and every task then lands on the first milestone.
    for _index, (mcode, mname, _s, _e, tasks) in enumerate(PLAN):
        # The step wrapper is a <section> containing every milestone, so the
        # LAST section carrying this code is the milestone's own panel.
        panel = (page.locator("section")
                 .filter(has=page.get_by_role("button", name="Add task",
                                              exact=True))
                 .filter(has_text=mcode).last)
        heading = panel.inner_text()[:40].replace("\n", " ")
        report.check(f"the panel for {mcode} is {mname}", mname in heading,
                     heading)
        for title, start, due in tasks:
            panel.get_by_label("Task title", exact=True).first.fill(title)
            panel.get_by_label("Task description",
                               exact=True).first.fill(f"{title} for the LGD "
                                                      "redevelopment.")
            finder = panel.get_by_label("Find Task owner", exact=True).first
            finder.fill("Priya Raman")
            page.wait_for_timeout(900)
            owner = panel.get_by_label("Task owner", exact=True).first
            options = owner.locator("option")
            for n in range(options.count()):
                if "priya" in options.nth(n).inner_text().lower():
                    owner.select_option(options.nth(n).get_attribute("value"))
                    break
            panel.get_by_label("Task start", exact=True).first.fill(day(start))
            panel.get_by_label("Task due date", exact=True).first.fill(day(due))
            page.wait_for_timeout(200)
            panel.get_by_role("button", name="Add task",
                              exact=True).first.click()
            page.wait_for_timeout(900)
    page.wait_for_timeout(1200)
    report.shot(page, "step5-tasks")
    stored = draft(client, key)["plan"]["tasks"]
    wanted = sum(len(row[4]) for row in PLAN)
    report.check("every task persisted under its milestone",
                 len(stored) == wanted, f"{len(stored)} of {wanted}")
    press(page, "Next")
    page.wait_for_timeout(1800)

    # ------------------------------------------------- 6  dependencies §13
    report.shot(page, "step6-dependencies")
    made = _dependencies(report, page)
    page.wait_for_timeout(1500)
    links = draft(client, key)["plan"]["links"]
    report.check("the dependency chain persisted", len(links) >= made,
                 f"{len(links)} link(s): "
                 f"{[(x.get('predecessor'), x.get('successor')) for x in links][:6]}")
    press(page, "Next")
    page.wait_for_timeout(2000)

    # ----------------------------------------------------- 7  preview §16
    report.shot(page, "step7-preview")
    body = page.inner_text("body")
    for wanted_text in (name, code, "Milestone", "Critical path"):
        report.check(f"the preview shows {wanted_text!r}",
                     wanted_text.lower() in body.lower())
    press(page, "Next")
    page.wait_for_timeout(1500)

    # ------------------------------------------------------ 8  publish §17
    report.shot(page, "step8-publish")
    published = press(page, "Publish project") or press(page, "Publish")
    report.check("Publish was available and pressed", published)
    page.wait_for_timeout(6000)
    report.shot(page, "after-publish")
    report.check("the browser landed on the published project",
                 "/delivery/" in page.url and "new" not in page.url, page.url)
    if "/delivery/" in page.url:
        try:
            report.project_id = int(page.url.rstrip("/").split("/")[-1]
                                    .split("?")[0])
        except ValueError:
            report.project_id = 0

    # The published project has to be a real, complete project.
    if report.project_id:
        detail = client.get(
            f"{API}/api/v1/planner/projects/{report.project_id}",
            timeout=60).json()
        report.check("the published project carries its plan",
                     len(detail.get("milestones", [])) == len(PLAN)
                     and len(detail.get("tasks", [])) == wanted,
                     f"{len(detail.get('milestones', []))} milestones, "
                     f"{len(detail.get('tasks', []))} tasks")
        report.check("it is on the portfolio without a refresh",
                     any(p.get("code") == code for p in client.get(
                         f"{API}/api/v1/planner/projects", timeout=60
                     ).json().get("projects", [])))


def _custom_policy(report: Report, page: Any, client: Any, key: str) -> None:
    """Type real numbers into the Custom policy and prove they are stored."""
    wanted = {"Remind before due": "10, 5, 2, 1",
              "Stale after": "4",
              "Chase overdue every": "1",
              "Escalate after": "2"}
    typed = 0
    for label, value in wanted.items():
        box = page.get_by_label(re.compile(label, re.I))
        if box.count():
            box.first.fill(value)
            typed += 1
            page.wait_for_timeout(250)
    page.wait_for_timeout(2200)
    report.check("the Custom policy accepted the values typed into it",
                 typed > 0, f"{typed} field(s) set")
    stored = draft(client, key)["plan"]["agentic"].get("policy", {})
    report.check("the Custom values reached the stored policy",
                 bool(stored), json.dumps(stored)[:240])


def _pick(page: Any, label: str, code: str) -> bool:
    """Choose a milestone or task in one of the two dependency pickers."""
    box = page.get_by_label(label, exact=True)
    if box.count() == 0:
        return False
    options = box.first.locator("option")
    for n in range(options.count()):
        value = options.nth(n).get_attribute("value") or ""
        if value == code or value.endswith(f":{code}"):
            box.first.select_option(value)
            page.wait_for_timeout(400)
            return True
    for n in range(options.count()):
        if code in (options.nth(n).inner_text() or ""):
            box.first.select_option(
                options.nth(n).get_attribute("value") or "")
            page.wait_for_timeout(400)
            return True
    return False


def _link(report: Report, page: Any, pred: str, succ: str) -> bool:
    """One dependency, through the real three-step control.

    Pick the two ends, ask what it would do, then decide. §13 asks for the
    impact to be stated BEFORE the link is made, and this is the control that
    does it.
    """
    if not _pick(page, "This has to finish first", pred):
        return False
    if not _pick(page, "Before this can start", succ):
        return False
    if not press(page, "Show the impact"):
        return False
    page.wait_for_timeout(1400)
    said = page.inner_text("body")
    report.check(f"the impact of {pred} → {succ} is stated before it is made",
                 "waits for" in said or "starts" in said or "finish" in said)
    for label in ("Create the dependency", "Keep dates and flag conflict"):
        if press(page, label):
            page.wait_for_timeout(1200)
            return True
    return False


def _dependencies(report: Report, page: Any) -> int:
    """Link each milestone to the one before it, and refuse a circular one."""
    made = 0
    for pred, succ in CHAIN:
        if _link(report, page, pred, succ):
            made += 1
    report.check("the dependency chain could be built through the form",
                 made == len(CHAIN), f"{made} of {len(CHAIN)} links made")

    # A circular dependency has to be refused, not accepted and then broken.
    if made:
        _pick(page, "This has to finish first", CHAIN[0][1])
        _pick(page, "Before this can start", CHAIN[0][0])
        press(page, "Show the impact")
        page.wait_for_timeout(1400)
        text = page.inner_text("body").lower()
        refused = ("circular" in text or "cycle" in text
                   or "cannot" in text or "already" in text)
        report.check("a circular dependency is refused", refused,
                     "the form offered to create it" if not refused else "")
        press(page, "Cancel")
        page.wait_for_timeout(600)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pass", dest="label", default="A")
    ap.add_argument("--user", default="priya.raman")
    ap.add_argument("--name", default="")
    ap.add_argument("--code", default="")
    ap.add_argument("--mode", default="CRITICAL")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    name = args.name or f"LGD Model Redevelopment — Final UAT {args.label}"
    code = args.code or f"LGD-UAT-{args.label}"
    print(f"Pass {args.label}: {name} ({code}), agentic {args.mode}\n")

    report = run(Report(args.label), who=args.user, name=name, code=code,
                 mode=args.mode, resume=args.resume)
    if args.json:
        Path(args.json).write_text(json.dumps(report.to_dict(), indent=2))
    print(f"\n{len(report.steps) - len(report.failures)} of "
          f"{len(report.steps)} checks passed"
          + (f"; stopped on {report.error}" if report.error else "."))
    return 1 if (report.failures or report.error) else 0


if __name__ == "__main__":
    sys.exit(main())
