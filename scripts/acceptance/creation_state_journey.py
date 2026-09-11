#!/usr/bin/env python
"""The form and the panels beside it, proved to be one document. §16, §17.

    .venv/bin/python scripts/acceptance/creation_state_journey.py
    .venv/bin/python scripts/acceptance/creation_state_journey.py --json

`uat_creation_journey.py` proves a project can be created. This proves the
thing UAT said was wrong with creating one: that the fields, the persisted
draft and the completeness panel could disagree — a sponsor chosen and a
panel still saying there was none — and that there was no single answer to
"has this saved?".

So after EVERY meaningful field it asserts three things at once:

    what the CONTROL holds
      == what the PERSISTED draft holds
      == what the COMPLETENESS engine says about it

and it fails if any two of them drift apart.

Around that it walks the rest of the remediation in a real browser:

    S1   there is one save model: no section Save buttons, one status line,
         and a field that saves itself without being told to
    S2   the progress bar is derived — it moves as fields are filled, and
         moves back when they are cleared
    S3   the assistant states the next step, and it is the first required
         thing missing
    S4   a completeness note is a button: pressing it lands on the step that
         owns the field, with that field focused
    S5   every field, one at a time: control == draft == completeness
    S6   a finished section collapses to a line worth reading
    S7   Custom opens a real configuration panel, and it persists and reloads
    S8   Publish is refused with a count while anything is required, and
         offered once nothing is
    S9   the whole plan survives a reload: nothing was only ever in the page

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
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

WEB = os.environ.get("CREDITPROBE_WEB", "http://localhost:3000").rstrip("/")
API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
WHO = os.environ.get("COPILOT_USER", "priya.raman")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2

WAIT_MS = 20_000
#: Long enough for the debounce to fire and the draft to be re-read. The
#: form saves ~700ms after the last keystroke; anything shorter here would
#: be testing the timer rather than the save.
SETTLE_MS = 2200

NAME = "Model Monitoring Framework UAT"
CODE = f"MMF-{uuid.uuid4().hex[:5].upper()}"
TODAY = date.today()
STARTS = TODAY + timedelta(days=7)
ENDS = TODAY + timedelta(days=180)


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


# ------------------------------------------------------------------ the DOM


def _anchor(field_: str) -> str:
    """The element id a completeness `field` addresses. Mirrors the form."""
    return "f-" + re.sub(r"[^a-zA-Z0-9]+", "-", field_)


def _labelled(page: Any, label: str) -> Any:
    return page.get_by_label(re.compile(rf"^{re.escape(label)}", re.I))


def _press(page: Any, name: str) -> None:
    page.get_by_role("button", name=re.compile(rf"^{re.escape(name)}$", re.I)
                     ).first.click()
    page.wait_for_timeout(400)


def _text(page: Any) -> str:
    return page.inner_text("body")


def _on_step(page: Any, number: int) -> bool:
    return f"step {number} of 8" in _text(page).lower()


def _type(page: Any, field_: str, value: str) -> None:
    """Put a value in a field and let the form save it of its own accord.

    Deliberately no button. The whole point of §2 is that nothing has to be
    pressed, so a journey that pressed something would be proving the wrong
    thing.
    """
    page.locator(f"#{_anchor(field_)}").fill(value)
    page.wait_for_timeout(SETTLE_MS)


def _pick(page: Any, field_: str, label: str, person: dict[str, Any]) -> None:
    _labelled(page, f"Find {label}").first.fill(
        str(person.get("username") or person.get("name") or ""))
    page.wait_for_timeout(900)
    select = page.locator(f"#{_anchor(field_)}")
    select.locator(f'option[value="{person["user_id"]}"]').wait_for(
        state="attached", timeout=WAIT_MS)
    select.select_option(value=str(person["user_id"]))
    page.wait_for_timeout(SETTLE_MS)


# -------------------------------------------------------- reading the truth


class Truth:
    def __init__(self, page: Any) -> None:
        self.page = page
        self.last_error = ""

    def _get(self, path: str) -> dict[str, Any]:
        found = self.page.request.get(f"{API}{path}")
        if not found.ok:
            self.last_error = (f"GET {path} -> {found.status} "
                               f"{found.text()[:200]}")
            return {}
        return found.json()

    def drafts(self) -> list[dict[str, Any]]:
        return self._get("/api/v1/planner/copilot/drafts").get("drafts", [])

    def draft(self, key: str) -> dict[str, Any]:
        return self._get(f"/api/v1/planner/copilot/drafts/{key}")

    def people(self) -> list[dict[str, Any]]:
        return self._get(
            "/api/v1/planner/copilot/people?limit=200").get("people", [])

    def me(self) -> dict[str, Any]:
        return self._get("/api/v1/auth/me").get("user") or {}

    def discard(self, key: str) -> bool:
        return bool(self.page.request.delete(
            f"{API}/api/v1/planner/copilot/drafts/{key}").ok)


def _newest(truth: Truth) -> dict[str, Any]:
    rows = [row for row in truth.drafts() if row.get("status") == "DRAFTING"]
    rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return rows[0] if rows else {}


def _said(found: dict[str, Any]) -> str:
    """Every completeness sentence about this draft, lowercased."""
    completeness = found.get("completeness") or {}
    return " ".join(
        str(note.get("message", "")).lower()
        for note in [*completeness.get("blockers", []),
                     *completeness.get("warnings", [])])


# ------------------------------------------------------------------ runner


def run(report: Report) -> Report:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        report.error = ("Playwright is not installed. The state journey did "
                        "not run and is NOT passed.")
        return report

    with sync_playwright() as play:
        try:
            browser = play.chromium.launch(executable_path=_chromium())
        except Exception as exc:  # noqa: BLE001
            report.error = (f"Chromium would not launch: {exc}. The state "
                            "journey did not run and is NOT passed.")
            return report
        context = browser.new_context(viewport={"width": 1600, "height": 1300},
                                      reduced_motion="reduce")
        page = context.new_page()
        crashes: list[str] = []
        page.on("pageerror", lambda exc: crashes.append(str(exc)[:200]))
        try:
            if not _sign_in(page, report):
                return report
            _journey(page, report, crashes)
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
                            "already signed in")
    page.fill("input[name=username], #username", WHO)
    page.fill("input[name=password], #password", DEMO_PASSWORD)
    page.click("button[type=submit]")
    try:
        page.wait_for_selector("input[name=password], #password",
                               state="detached", timeout=WAIT_MS)
    except Exception:  # noqa: BLE001
        report.error = f"could not sign in as {WHO}. Run scripts/seed_planner.py."
        return False
    return report.check("sign in", f"signed in as {WHO}", True)


def _journey(page: Any, report: Report, crashes: list[str]) -> None:
    truth = Truth(page)
    me = truth.me()
    if not report.check("setup", "the signed-in person can be named on a plan",
                        bool(me.get("id")), truth.last_error):
        return
    person = {"user_id": int(me["id"]),
              "username": str(me.get("username") or WHO),
              "name": str(me.get("full_name") or me.get("username") or WHO)}

    page.goto(f"{WEB}/delivery/new", wait_until="networkidle")
    page.wait_for_timeout(1200)
    _press(page, "Start the setup")
    page.wait_for_timeout(1800)

    key = str(_newest(truth).get("key") or "")
    if not report.check("setup", "a draft was started server-side", bool(key),
                        truth.last_error):
        return

    try:
        _s1_one_save(page, report, truth, key)
        _s2_progress(page, report, truth, key)
        _s3_assistant(page, report, truth, key)
        _s4_clickable(page, report)
        _s5_every_field(page, report, truth, key, person)
        _s6_collapsed(page, report)
        _s7_custom(page, report, truth, key)
        _s8_publish(page, report, truth, key, person)
        _s9_reload(page, report, truth, key)
        report.check("flow", "nothing on the page threw", not crashes,
                     "; ".join(crashes[:3]))
    finally:
        truth.discard(key)


# ------------------------------------------------------------ S1 one save


def _s1_one_save(page: Any, report: Report, truth: Truth, key: str) -> None:
    saves = [" ".join((button.inner_text() or "").split())
             for button in page.get_by_role("button").all()
             if "save" in (button.inner_text() or "").lower()]
    report.check("S1", "there is exactly one Save control on the form",
                 saves == ["Save draft"], f"found {saves}")
    report.check("S1", "there are no section-level Save buttons",
                 not any(word in " ".join(saves).lower()
                         for word in ("save milestone", "save task",
                                      "save section", "save changes")),
                 f"found {saves}")
    report.check("S1", "there is no chat box on the form",
                 page.locator("textarea").count() == 0,
                 f"{page.locator('textarea').count()} textareas")

    body = _text(page)
    report.check("S1", "the form says every field saves itself",
                 "saves itself" in body.lower(), body[-400:])

    # And it does: type, press nothing, and read the server.
    page.locator(f"#{_anchor('overview.name')}").fill(NAME)
    page.wait_for_timeout(SETTLE_MS)
    stored = (truth.draft(key).get("plan") or {}).get("overview", {})
    report.check("S1", "a field saves without anything being pressed",
                 stored.get("name") == NAME,
                 f"the draft holds {stored.get('name')!r}")
    report.check("S1", "one status line says so",
                 "saved" in _text(page).lower(), _text(page)[-300:])


# ------------------------------------------------------------ S2 progress


def _s2_progress(page: Any, report: Report, truth: Truth, key: str) -> None:
    body = _text(page).lower()
    report.check("S2", "the form says how many sections are complete",
                 bool(re.search(r"\d of 8 sections complete", body)),
                 body[-500:])
    report.check("S2", "there is a progress bar",
                 page.locator("[role=progressbar]").count() > 0)

    found = truth.draft(key)
    sections = (found.get("progress") or {}).get("sections") or []
    report.check("S2", "the progress covers all eight sections",
                 len(sections) == 8, f"{len(sections)} sections")
    report.check("S2", "every section carries a state",
                 all(row.get("state") for row in sections))

    # Derived, not stored: fill the overview and watch it move.
    before = (found.get("progress") or {}).get("complete")
    for field_, value in (("overview.code", CODE),
                          ("overview.description", "Rebuild the framework."),
                          ("overview.objective", "Signed off by Model Risk.")):
        _type(page, field_, value)
    after = ((truth.draft(key).get("progress") or {}).get("complete"))
    report.check("S2", "filling a section moves the count up",
                 isinstance(after, int) and isinstance(before, int)
                 and after > before, f"{before} -> {after}")

    overview = next((row for row in
                     (truth.draft(key).get("progress") or {}).get("sections")
                     if row["key"] == "overview"), {})
    report.check("S2", "the finished section reads Complete",
                 overview.get("state") == "complete", str(overview))

    # And back down when it is cleared.
    page.locator(f"#{_anchor('overview.code')}").fill("")
    page.wait_for_timeout(SETTLE_MS)
    cleared = next((row for row in
                    (truth.draft(key).get("progress") or {}).get("sections")
                    if row["key"] == "overview"), {})
    report.check("S2", "clearing a required field moves it back",
                 cleared.get("state") == "needs_attention", str(cleared))
    _type(page, "overview.code", CODE)


# ----------------------------------------------------------- S3 assistant


def _s3_assistant(page: Any, report: Report, truth: Truth, key: str) -> None:
    body = _text(page)
    report.check("S3", "the panel is a project setup assistant",
                 "project setup assistant" in body.lower())
    report.check("S3", "it names the next recommended step",
                 "next recommended step" in body.lower())
    report.check("S3", "it offers actions for the step you are on",
                 "on this step" in body.lower())
    report.check("S3", "it cannot be talked to",
                 page.locator("textarea").count() == 0
                 and page.get_by_role(
                     "button", name=re.compile(r"^(send|ask)$", re.I)
                 ).count() == 0)

    said = truth.draft(key).get("guidance") or {}
    report.check("S3", "the next step is the first required thing missing",
                 said.get("next", {}).get("required") is True
                 and said["next"]["field"].startswith("governance."),
                 str(said.get("next")))
    report.check("S3", "the assistant says what is settled",
                 any("Overview" in row.get("section", "")
                     for row in said.get("complete") or []),
                 str(said.get("complete")))


# ----------------------------------------------------------- S4 clickable


def _s4_clickable(page: Any, report: Report) -> None:
    """§9. A note about the sponsor is one press away from the sponsor."""
    note = page.get_by_role(
        "button", name=re.compile(r"^Fix: The project has no sponsor",
                                  re.I)).first
    report.check("S4", "the missing sponsor is offered as something to press",
                 note.count() > 0)
    if note.count() == 0:
        return
    note.click()
    page.wait_for_timeout(1800)
    report.check("S4", "pressing it lands on the step that owns the field",
                 _on_step(page, 2), _text(page)[-300:])
    focused = page.evaluate("document.activeElement && document.activeElement.id")
    report.check("S4", "and the field itself has the cursor",
                 focused == _anchor("governance.sponsor_id"),
                 f"focus is on {focused!r}")


# -------------------------------------------------- S5 field by field, §16


def _s5_every_field(page: Any, report: Report, truth: Truth, key: str,
                    person: dict[str, Any]) -> None:
    """After each field: the control, the draft and the completeness agree."""
    gone: list[str] = []

    def settled(where: str, field_: str, expect: Any, sentence: str) -> None:
        found = truth.draft(key)
        plan = found.get("plan") or {}
        section, name = field_.split(".", 1)
        held = (plan.get(section) or {}).get(name)
        report.check("S5", f"{where}: the draft holds what was entered",
                     held == expect, f"draft holds {held!r}, wanted {expect!r}")

        shown = page.locator(f"#{_anchor(field_)}").input_value()
        report.check("S5", f"{where}: the control still shows it",
                     str(shown) == str(expect or ""),
                     f"the control shows {shown!r}")

        gone.append(sentence)
        still = _said(found)
        stale = [line for line in gone if line in still]
        report.check("S5", f"{where}: the completeness stops saying it is missing",
                     not stale, f"still saying {stale}")

        panel = _text(page).lower()
        left = [line for line in gone if line in panel]
        report.check("S5", f"{where}: and the panel on screen agrees",
                     not left, f"the page still says {left}")

    for label, field_ in (("Sponsor", "governance.sponsor_id"),
                          ("Project manager", "governance.manager_id"),
                          ("Owner", "governance.owner_id"),
                          ("Escalation contact", "governance.escalation_id")):
        _pick(page, field_, label, person)
        settled(label.lower(), field_, person["user_id"],
                {"Sponsor": "the project has no sponsor.",
                 "Project manager": "the project has no manager.",
                 "Owner": "the project has no owner.",
                 "Escalation contact": "there is nobody to escalate to."}[label])

    _type(page, "governance.start_date", STARTS.isoformat())
    settled("start date", "governance.start_date", STARTS.isoformat(),
            "the project has no start date.")
    _type(page, "governance.target_end_date", ENDS.isoformat())
    settled("target completion", "governance.target_end_date", ENDS.isoformat(),
            "the project has no target completion date.")

    body = _text(page).lower()
    for never in ("no sponsor", "no project manager", "nobody to escalate",
                  "no start date", "no target completion"):
        report.check("S5", f"the page never goes back to saying {never!r}",
                     never not in body, body[-600:])


# ----------------------------------------------------------- S6 collapsed


def _s6_collapsed(page: Any, report: Report) -> None:
    """§12. A finished section shows what it holds, not its fields."""
    rail = page.get_by_role("button", name=re.compile(r"^1 Overview", re.I))
    report.check("S6", "the finished Overview collapses to a summary",
                 rail.count() > 0
                 and CODE.lower() in (rail.first.inner_text() or "").lower(),
                 rail.first.inner_text() if rail.count() else "no rail entry")
    governance = page.get_by_role(
        "button", name=re.compile(r"^2 People and governance", re.I))
    report.check("S6", "so does People and governance",
                 governance.count() > 0
                 and "sponsor" in (governance.first.inner_text() or "").lower(),
                 governance.first.inner_text() if governance.count() else "")
    report.check("S6", "only the step being worked on is open",
                 _text(page).lower().count("step ") >= 1
                 and page.locator("#" + _anchor("overview.name")).count() == 0,
                 "the overview fields are still on screen")


# -------------------------------------------------------------- S7 custom


def _s7_custom(page: Any, report: Report, truth: Truth, key: str) -> None:
    _press(page, "Next")
    page.wait_for_timeout(1600)
    report.check("S7", "the agentic policy step is reached", _on_step(page, 3),
                 _text(page)[-300:])

    page.get_by_role("button", name=re.compile(r"^Custom", re.I)).first.click()
    page.wait_for_timeout(SETTLE_MS)
    report.check("S7", "choosing Custom opens a configuration panel",
                 page.get_by_label("Custom agentic policy").count() > 0,
                 _text(page)[-600:])

    escalate = _labelled(page, "Escalate an overdue task after this many days")
    report.check("S7", "the thresholds are real fields", escalate.count() > 0)
    if escalate.count() == 0:
        return
    escalate.first.fill("1")
    page.wait_for_timeout(SETTLE_MS)

    stored = ((truth.draft(key).get("plan") or {}).get("agentic") or {})
    report.check("S7", "the threshold is persisted",
                 stored.get("mode") == "CUSTOM"
                 and stored.get("policy", {}).get("escalate_after_days") == 1,
                 str(stored))
    said = (truth.draft(key).get("agentic_policy") or {}).get("sentence", "")
    report.check("S7", "the policy is read back in words",
                 "overdue after 1 day is escalated" in said, said[:200])
    report.check("S7", "and those words are on the screen",
                 "overdue after 1 day is escalated" in _text(page),
                 _text(page)[-800:])

    # Reload: it is still set.
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2000)
    report.check("S7", "it survives a reload",
                 "1" == _labelled(
                     page, "Escalate an overdue task after this many days"
                 ).first.input_value(),
                 "the field came back empty")


# ------------------------------------------------------------- S8 publish


def _s8_publish(page: Any, report: Report, truth: Truth, key: str,
                person: dict[str, Any]) -> None:
    found = truth.draft(key)
    message = (found.get("progress") or {}).get("publish_message", "")
    report.check("S8", "publish is refused with a count of what is left",
                 message.startswith("Publish unavailable —")
                 and "required item" in message, message)
    report.check("S8", "and that sentence is on the screen",
                 message in _text(page), _text(page)[-600:])

    # Finish the plan through the API — the form's own path is proved by
    # uat_creation_journey; what is under test here is the publish gate.
    for command, payload in (
            ("add_milestone", {"name": "Framework build",
                               "owner_id": person["user_id"],
                               "start_date": STARTS.isoformat(),
                               "target_date": ENDS.isoformat()}),
            ("add_task", {"milestone_code": "M01", "title": "Draft it",
                          "owner_id": person["user_id"],
                          "description": "Write the framework.",
                          "start_date": STARTS.isoformat(),
                          "due_date": (STARTS + timedelta(days=30)
                                       ).isoformat()})):
        page.request.post(
            f"{API}/api/v1/planner/copilot/drafts/{key}/apply",
            data={"command": command, "payload": payload})

    page.reload(wait_until="networkidle")
    page.wait_for_timeout(2200)
    after = truth.draft(key)
    report.check("S8", "once nothing is required, it says so",
                 (after.get("progress") or {}).get("publish_message")
                 == "Everything required is in place.",
                 str((after.get("progress") or {}).get("publish_message")))

    # Walk to the last step and check the button.
    for _ in range(8):
        if _on_step(page, 8):
            break
        _press(page, "Next")
        page.wait_for_timeout(1400)
    report.check("S8", "the last step is reachable", _on_step(page, 8),
                 _text(page)[-300:])
    publish = page.get_by_role("button", name=re.compile(r"^Publish project$",
                                                         re.I))
    report.check("S8", "Publish is in the action bar", publish.count() > 0)
    report.check("S8", "and it is now offered",
                 publish.count() > 0 and publish.first.is_enabled())
    for expected in ("Back", "Save draft", "Preview", "Publish project"):
        report.check("S8", f"the last action bar has {expected!r}",
                     page.get_by_role(
                         "button", name=re.compile(rf"^{expected}$", re.I)
                     ).count() > 0)


# -------------------------------------------------------------- S9 reload


def _s9_reload(page: Any, report: Report, truth: Truth, key: str) -> None:
    page.goto(f"{WEB}/delivery/new?draft={key}", wait_until="networkidle")
    page.wait_for_timeout(2200)
    plan = (truth.draft(key).get("plan") or {})
    report.check("S9", "the plan came back whole",
                 plan.get("overview", {}).get("name") == NAME
                 and plan.get("governance", {}).get("sponsor_id")
                 and len(plan.get("milestones") or []) == 1
                 and len(plan.get("tasks") or []) == 1,
                 json.dumps(plan.get("overview", {})))
    body = _text(page)
    report.check("S9", "and the reopened form shows it",
                 NAME in body or CODE in body, body[-500:])
    report.check("S9", "nothing was only ever in the page",
                 "sections complete" in body.lower(), body[-500:])


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
                print(f"        {step.detail}")
        if report.error:
            print(f"\nERROR: {report.error}")
        found = report.to_dict()
        print(f"\n{found['passed']} passed, {found['failed']} failed")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
