#!/usr/bin/env python
"""Pass C — the project somebody actually builds: interrupted, then finished.

§50 C of the final UAT. Pass A walks the happy path and Pass B configures
the agent. This one is the awkward, realistic version:

  * a plan started, part-filled, and abandoned mid-step;
  * the browser CLOSED — not navigated away, closed — and reopened later,
    the way somebody comes back after a meeting;
  * the draft found again from the Project Planner home, not from a URL
    that happened to still be in the address bar;
  * work spread across SEVERAL people rather than assigned to whoever is
    signed in, because a plan with one owner proves nothing about a plan;
  * a task somebody is BLOCKED on, with the reason written down;
  * a RAID entry raised against a real risk;
  * the whole thing exported to a workbook and read back in, so that what
    leaves the product is what comes back into it (§35 to §37, §46).

Everything that a person would do is done through the browser. The
workbook round-trip is done through the product's own API because a
browser download is a file on disk and the question being asked is about
the CONTENT, not about the click — but the screen is still checked for
the buttons that start it.

    python -m scripts.acceptance.final_uat_pass_c \\
        --name "Collections Strategy Refresh — Final UAT C" --code COL-UAT-C
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
    "/tmp/claude-0/-home-user-IPM-V2/"
    "5ffce7b7-1bec-5104-89bb-0340b35118dd/scratchpad/shots"))
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
TODAY = date.today()

#: Two milestones is enough to prove the shape; the point of this pass is
#: what happens AROUND the plan, not the size of it. The owners differ on
#: purpose — a plan where every task belongs to the person filling the form
#: cannot show that the product asks the right person for an update.
PLAN = [
    ("M01", "Strategy Design", 10, 70, [
        ("Segment the book", "Priya Raman", 12, 30),
        ("Draft the treatment rules", "Daniel Okafor", 25, 55),
    ]),
    ("M02", "Build and Test", 60, 150, [
        ("Implement the rules", "Omar Nasser", 62, 110),
        ("Test against last year", "Daniel Okafor", 100, 140),
    ]),
]


def anchor(name: str) -> str:
    return "#f-" + re.sub(r"[^a-zA-Z0-9]+", "-", name)


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


class Report:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.error = ""
        self.key = ""
        self.project_id = 0
        self.shot_n = 0

    def check(self, what: str, ok: bool, said: str = "") -> bool:
        self.steps.append({"step": what, "ok": bool(ok), "said": said})
        print(f"  {'PASS' if ok else 'FAIL'}  {what}"
              + (f"\n        {said}" if said else ""), flush=True)
        return bool(ok)

    def shot(self, page: Any, name: str) -> None:
        self.shot_n += 1
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / f"C-{self.shot_n:02d}-{name}.png"))

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if not s["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "error": self.error, "key": self.key,
                "project_id": self.project_id,
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures)}


# --------------------------------------------------------------- the browser

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


def press(page: Any, label: str, *, exact: bool = True) -> bool:
    button = page.get_by_role("button", name=label, exact=exact)
    if button.count() == 0:
        return False
    button.first.click()
    page.wait_for_timeout(700)
    return True


def choose_person(page: Any, label: str, name: str) -> bool:
    """Type a name into a picker's search box and take the match."""
    finder = page.get_by_label(f"Find {label}", exact=True)
    if finder.count():
        finder.first.fill(name)
        page.wait_for_timeout(1000)
    box = page.get_by_label(label, exact=True)
    if box.count() == 0:
        return False
    options = box.first.locator("option")
    for n in range(options.count()):
        if name.lower() in (options.nth(n).inner_text() or "").lower():
            box.first.select_option(options.nth(n).get_attribute("value") or "")
            page.wait_for_timeout(400)
            return True
    return False


def draft(client: Any, key: str) -> dict[str, Any]:
    out = client.get(f"{API}/api/v1/planner/copilot/drafts/{key}", timeout=60)
    out.raise_for_status()
    return out.json()


# ------------------------------------------------------------- the four acts

def _start_and_walk_away(report: Report, page: Any, client: Any, *,
                         name: str, code: str) -> str:
    """Fill the first two steps, then stop — no Save, no Publish."""
    page.goto(f"{WEB}/delivery/new", wait_until="networkidle")
    page.wait_for_timeout(1500)
    press(page, "Start the setup", exact=False)
    page.wait_for_timeout(2500)
    key = page.url.split("draft=")[1].split("&")[0] if "draft=" in page.url \
        else ""
    report.check("a new plan gets a draft of its own", bool(key), page.url)
    if not key:
        return ""

    page.fill(anchor("overview.name"), name)
    page.fill(anchor("overview.code"), code)
    page.fill(anchor("overview.description"),
              "Refresh the collections treatment strategy for the retail "
              "unsecured book.")
    page.fill(anchor("overview.objective"),
              "A tested, approved collections strategy in production.")
    page.wait_for_timeout(2400)
    press(page, "Next")
    page.wait_for_timeout(2000)

    for label, person in (("Sponsor", "Amina Hassan"),
                          ("Project manager", "Priya Raman"),
                          ("Owner", "Daniel Okafor"),
                          ("Escalation contact", "Amina Hassan")):
        report.check(f"{label} could be set to {person}",
                     choose_person(page, label, person))
    page.fill(anchor("governance.start_date"), day(0))
    page.fill(anchor("governance.target_end_date"), day(180))
    page.wait_for_timeout(2400)
    report.shot(page, "part-filled")

    held = draft(client, key)["plan"]
    report.check("what was typed is already saved, with nothing pressed",
                 held["overview"].get("name") == name
                 and bool(held["governance"].get("sponsor_id")),
                 f"{held['overview'].get('name')!r}, sponsor="
                 f"{held['governance'].get('sponsor_id')}")
    return key


def _come_back_later(report: Report, page: Any, client: Any, *,
                     name: str, code: str, key: str) -> bool:
    """Find the draft from the home page, not from a remembered URL."""
    page.goto(f"{WEB}/delivery", wait_until="networkidle")
    page.wait_for_timeout(2500)
    report.shot(page, "home-with-draft")

    body = page.inner_text("body")
    report.check("the unfinished plan is waiting on the Project Planner home",
                 code in body,
                 "Draft projects lists: "
                 + ", ".join(re.findall(r"[A-Z][A-Z0-9-]{4,}", body))[:120])
    report.check("the draft says it is not published and nobody is being "
                 "chased about it",
                 "not published" in body.lower())

    # The row offers to continue it. That link is the way back in.
    # By CODE, not by name: a code is unique across the estate, and two
    # runs of this script share a name.
    row = page.locator("li").filter(has_text=code).last
    link = row.get_by_role("link", name="Continue editing")
    found = link.count() > 0
    report.check("the draft offers a way back into it", found)
    if not found:
        return False
    link.first.click()
    page.wait_for_timeout(4000)
    report.shot(page, "resumed")

    report.check("continuing lands back in the same draft",
                 key in page.url, page.url)
    value = page.locator(anchor("overview.name"))
    shown = value.first.input_value() if value.count() else ""
    if not shown:
        # The form reopens on the step it was left on, which is the right
        # behaviour; step 1 is then one press away.
        press(page, "Back")
        page.wait_for_timeout(1500)
        value = page.locator(anchor("overview.name"))
        shown = value.first.input_value() if value.count() else ""
    report.check("everything typed before the break is still on the screen",
                 shown == name, f"the name box reads {shown!r}")
    gov = draft(client, key)["plan"]["governance"]
    report.check("and so is everybody who was named",
                 all(gov.get(f) for f in ("sponsor_id", "manager_id",
                                          "owner_id", "escalation_id")),
                 json.dumps({k: gov.get(k) for k in
                             ("sponsor_id", "manager_id", "owner_id",
                              "escalation_id")}))
    report.check("the code survived the break too",
                 draft(client, key)["plan"]["overview"].get("code") == code)
    return True


def _finish_the_plan(report: Report, page: Any, client: Any,
                     key: str) -> None:
    """Milestones and tasks, with the work spread across several people."""
    # Walk forward to the milestones step.
    for _ in range(6):
        if page.get_by_label("Milestone name", exact=True).count():
            break
        if not press(page, "Next"):
            break
        page.wait_for_timeout(1600)

    report.check("the plan reaches the milestones step",
                 page.get_by_label("Milestone name", exact=True).count() > 0)
    for _mcode, mname, start, end, _tasks in PLAN:
        page.get_by_label("Milestone name", exact=True).first.fill(mname)
        choose_person(page, "Milestone owner", "Priya Raman")
        page.get_by_label("Milestone start", exact=True).first.fill(day(start))
        page.get_by_label("Milestone target date",
                          exact=True).first.fill(day(end))
        page.wait_for_timeout(300)
        press(page, "Add milestone")
        page.wait_for_timeout(1100)
    stones = draft(client, key)["plan"]["milestones"]
    report.check("both milestones persisted", len(stones) == len(PLAN),
                 f"{len(stones)}: {[m.get('code') for m in stones]}")
    press(page, "Next")
    page.wait_for_timeout(1800)

    for mcode, mname, _s, _e, tasks in PLAN:
        panel = (page.locator("section")
                 .filter(has=page.get_by_role("button", name="Add task",
                                              exact=True))
                 .filter(has_text=mcode).last)
        report.check(f"the panel for {mcode} is {mname}",
                     mname in panel.inner_text()[:40])
        for title, owner_name, start, due in tasks:
            panel.get_by_label("Task title", exact=True).first.fill(title)
            panel.get_by_label("Task description", exact=True).first.fill(
                f"{title}, for the collections strategy refresh.")
            finder = panel.get_by_label("Find Task owner", exact=True).first
            finder.fill(owner_name)
            page.wait_for_timeout(1000)
            owner = panel.get_by_label("Task owner", exact=True).first
            options = owner.locator("option")
            picked = False
            for n in range(options.count()):
                if owner_name.lower() in (options.nth(n).inner_text()
                                          or "").lower():
                    owner.select_option(
                        options.nth(n).get_attribute("value") or "")
                    picked = True
                    break
            report.check(f"{title} could be given to {owner_name}", picked)
            panel.get_by_label("Task start", exact=True).first.fill(day(start))
            panel.get_by_label("Task due date", exact=True).first.fill(day(due))
            page.wait_for_timeout(200)
            panel.get_by_role("button", name="Add task",
                              exact=True).first.click()
            page.wait_for_timeout(900)
    page.wait_for_timeout(1200)
    report.shot(page, "tasks-several-people")

    held = draft(client, key)["plan"]["tasks"]
    wanted = sum(len(row[4]) for row in PLAN)
    report.check("every task persisted", len(held) == wanted,
                 f"{len(held)} of {wanted}")
    owners = {t.get("owner_id") for t in held if t.get("owner_id")}
    report.check("the work is spread across several people, not one",
                 len(owners) >= 3, f"{len(owners)} distinct owner(s): {owners}")

    # Forward through dependencies and preview to Publish. The match has to
    # be exact: the completeness strip carries a clickable "Ready to publish"
    # chip, and a loose match on "Publish" stops the walk on step five.
    for _ in range(5):
        if page.get_by_role("button", name="Publish project",
                            exact=True).count():
            break
        if not press(page, "Next"):
            break
        page.wait_for_timeout(1800)
    report.shot(page, "before-publish")
    report.check("Publish was available and pressed",
                 press(page, "Publish project"))
    page.wait_for_timeout(6000)
    report.shot(page, "published")
    report.check("the browser landed on the published project",
                 "/delivery/" in page.url and "new" not in page.url, page.url)
    if "/delivery/" in page.url:
        try:
            report.project_id = int(
                page.url.rstrip("/").split("/")[-1].split("?")[0])
        except ValueError:
            report.project_id = 0


def _blocked_and_raid(report: Report, page: Any, client: Any,
                      project_id: int) -> None:
    """Something is stuck, and somebody writes down why (§32)."""
    detail = client.get(f"{API}/api/v1/planner/projects/{project_id}",
                        timeout=60).json()
    tasks = detail.get("tasks", [])
    report.check("the published project has work in it", bool(tasks),
                 f"{len(tasks)} task(s)")
    if not tasks:
        return
    stuck = tasks[0]
    why = ("Waiting on the data team for the treatment history extract. "
           "Nothing can be segmented until it lands.")
    out = client.patch(f"{API}/api/v1/planner/tasks/{stuck['id']}", timeout=60,
                       json={"status": "BLOCKED", "blocker_reason": why,
                             "version": stuck["version"]})
    report.check("a task can be marked blocked, with the reason",
                 out.status_code == 200,
                 f"HTTP {out.status_code} {out.text[:160]}")

    again = client.get(f"{API}/api/v1/planner/projects/{project_id}",
                       timeout=60).json()
    now = next((t for t in again["tasks"] if t["id"] == stuck["id"]), {})
    report.check("the block persisted, with the reason kept",
                 now.get("status") == "BLOCKED"
                 and "data team" in (now.get("blocker_reason") or ""),
                 f"{now.get('status')}: "
                 f"{(now.get('blocker_reason') or '')[:70]}")

    raid = client.post(f"{API}/api/v1/planner/projects/{project_id}/raid",
                       timeout=60,
                       json={"kind": "RISK", "severity": "HIGH",
                             "title": "Treatment history extract may be late",
                             "description":
                                 "The data team has not committed to a date. "
                                 "If it slips past the segmentation window "
                                 "the build start moves with it.",
                             "mitigation":
                                 "Escalate to the data steward this week and "
                                 "agree a date in writing."})
    report.check("a risk can be raised against the project",
                 raid.status_code in (200, 201),
                 f"HTTP {raid.status_code} {raid.text[:160]}")

    after = client.get(f"{API}/api/v1/planner/projects/{project_id}",
                       timeout=60).json()
    items = after.get("raid", [])
    report.check("the risk is on the project", bool(items),
                 f"{len(items)} RAID item(s)")

    # And a person has to be able to SEE both without asking anyone.
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.wait_for_timeout(3000)
    report.shot(page, "blocked-and-raid")
    body = page.inner_text("body")
    report.check("the project screen says something is blocked",
                 "blocked" in body.lower())
    report.check("the project screen shows the risk that was raised",
                 "treatment history extract may be late" in body.lower(),
                 "the risk title is nowhere on the Overview"
                 if "treatment history" not in body.lower() else "")


def _workbook_round_trip(report: Report, page: Any, client: Any,
                         project_id: int, code: str) -> None:
    """What leaves the product has to be what comes back in (§35 to §37)."""
    page.goto(f"{WEB}/delivery/{project_id}", wait_until="networkidle")
    page.wait_for_timeout(2500)
    body = page.inner_text("body").lower()
    report.check("the project offers to export itself",
                 "export" in body or "excel" in body or "workbook" in body)

    got = client.get(f"{API}/api/v1/planner/projects/{project_id}/export",
                     timeout=120)
    report.check("the export downloads", got.status_code == 200,
                 f"HTTP {got.status_code}, {len(got.content):,} bytes")
    if got.status_code != 200:
        return
    report.check("it is a workbook, not an error page in disguise",
                 got.content[:2] == b"PK",
                 f"starts {got.content[:4]!r}, content-type "
                 f"{got.headers.get('content-type', '')[:60]}")

    import io

    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(got.content), read_only=True)
    text = ""
    for sheet in book.worksheets:
        for row in sheet.iter_rows(values_only=True):
            text += " ".join(str(c) for c in row if c is not None) + "\n"
    for wanted in (code, "Strategy Design", "Segment the book",
                   "Implement the rules"):
        report.check(f"the workbook carries {wanted!r}", wanted in text)
    named = [who for who in ("Daniel", "daniel.okafor", "Okafor")
             if who in text]
    report.check("the workbook names the people the work belongs to",
                 bool(named),
                 f"found {named}" if named
                 else "no owner name or username in any sheet")

    # Read it straight back in as a NEW project. Nothing is applied until a
    # second, deliberate call, so the preview is checked before committing.
    fresh = re.sub(r"[^A-Z0-9-]", "", code.upper())[:10] + "-RT"
    swapped = _recode(got.content, code, fresh)
    staged = client.post(f"{API}/api/v1/planner/imports", timeout=120,
                         files={"file": (f"{fresh}.xlsx", swapped,
                                         "application/vnd.openxmlformats-"
                                         "officedocument.spreadsheetml.sheet")})
    report.check("the exported workbook can be read back in",
                 staged.status_code == 200,
                 f"HTTP {staged.status_code} {staged.text[:200]}")
    if staged.status_code != 200:
        return
    preview = staged.json()
    report.check("reading it in changes nothing until somebody says so",
                 preview.get("mode") == "CREATE"
                 and bool(preview.get("import_id"))
                 and not preview.get("project_id"),
                 json.dumps({k: preview.get(k) for k in
                             ("mode", "import_id", "project_id",
                              "project_code")})[:220])
    problems = preview.get("errors") or preview.get("problems") or []
    report.check("the product found nothing wrong with its own export",
                 not problems, json.dumps(problems)[:200])

    done = client.post(
        f"{API}/api/v1/planner/imports/{preview['import_id']}/commit",
        timeout=120)
    report.check("committing the import creates the project",
                 done.status_code in (200, 201),
                 f"HTTP {done.status_code} {done.text[:200]}")
    if done.status_code not in (200, 201):
        return
    made = done.json().get("project_id")
    original = client.get(f"{API}/api/v1/planner/projects/{project_id}",
                          timeout=60).json()
    copy = client.get(f"{API}/api/v1/planner/projects/{made}",
                      timeout=60).json()
    report.check("the round trip kept every milestone",
                 len(copy.get("milestones", []))
                 == len(original.get("milestones", [])),
                 f"{len(copy.get('milestones', []))} vs "
                 f"{len(original.get('milestones', []))}")
    report.check("the round trip kept every task",
                 len(copy.get("tasks", [])) == len(original.get("tasks", [])),
                 f"{len(copy.get('tasks', []))} vs "
                 f"{len(original.get('tasks', []))}")
    report.check("the round trip kept the task titles",
                 sorted(t["title"] for t in copy.get("tasks", []))
                 == sorted(t["title"] for t in original.get("tasks", [])))
    # The detail payload carries the whole person, not an id — so read the
    # person. Comparing `owner_id` on both sides compares None with None and
    # passes whatever the product did, which is worse than not checking.
    def owners(rows: list[dict[str, Any]]) -> list[str]:
        return sorted((row.get("owner") or {}).get("username") or "nobody"
                      for row in rows)

    mine, theirs = owners(copy.get("tasks", [])), owners(
        original.get("tasks", []))
    report.check("every task in the copy still belongs to somebody",
                 "nobody" not in mine, f"copy owners {mine}")
    report.check("the round trip kept who each task belongs to",
                 mine == theirs, f"copy {mine} vs original {theirs}")


def _recode(content: bytes, old: str, new: str) -> bytes:
    """The same workbook with a different project code.

    Importing an export as a NEW project needs a code the estate does not
    already hold — otherwise the product is right to refuse it, and the
    round trip would be proving the duplicate check rather than the export.
    """
    import io

    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(content))
    for sheet in book.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and old in cell.value:
                    cell.value = cell.value.replace(old, new)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# ------------------------------------------------------------------- driving

def run(report: Report, *, who: str, name: str, code: str) -> Report:
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
        errors: list[str] = []

        # ---- act one: start it, and be interrupted.
        first = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = first.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        sign_in(page, who, DEMO_PASSWORD)
        key = _start_and_walk_away(report, page, client,
                                   name=name, code=code)
        report.key = key
        # Closing the CONTEXT throws away the tab, its memory and its
        # cookies. Whatever comes back has to come back from the server.
        first.close()
        report.check("the browser was closed on an unfinished plan", True,
                     "context discarded, cookies included")
        if not key:
            report.error = "no draft was created"
            browser.close()
            return report

        # ---- act two: come back and find it.
        second = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = second.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)[:160]))
        sign_in(page, who, DEMO_PASSWORD)
        if _come_back_later(report, page, client,
                            name=name, code=code, key=key):
            _finish_the_plan(report, page, client, key)

        # ---- act three: the things that go wrong on a real project.
        if report.project_id:
            _blocked_and_raid(report, page, client, report.project_id)
            _workbook_round_trip(report, page, client, report.project_id, code)

        report.check("the browser reported no uncaught error",
                     not errors, "; ".join(errors[:3]))
        browser.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default="priya.raman")
    ap.add_argument("--name",
                    default="Collections Strategy Refresh — Final UAT C")
    ap.add_argument("--code", default="COL-UAT-C")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"Pass C — {args.name} ({args.code})\n")
    report = Report()
    try:
        run(report, who=args.user, name=args.name, code=args.code)
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
