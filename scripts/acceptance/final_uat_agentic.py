#!/usr/bin/env python
"""What the Agentic AI actually does, demonstrated rather than described.

§26 to §29 of the final UAT: make something late, run the agent, and check
that a named person was told, that the message says what it is about, that
the Agent Activity records it, that running again does not send it twice,
and that a delay that nobody resolves climbs the ladder to the escalation
contact and stops there.

Everything is done through the product's own API as a signed-in person —
the task dates are moved the way a project manager moves them, and the
messages are read out of the recipient's own inbox.

    python -m scripts.acceptance.final_uat_agentic --project 2867
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
TODAY = date.today()


class Report:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.error = ""

    def check(self, what: str, ok: bool, said: str = "") -> bool:
        self.steps.append({"step": what, "ok": bool(ok), "said": said})
        print(f"  {'PASS' if ok else 'FAIL'}  {what}"
              + (f"\n        {said}" if said else ""), flush=True)
        return bool(ok)

    @property
    def failures(self) -> list[dict[str, Any]]:
        return [s for s in self.steps if not s["ok"]]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": self.steps, "error": self.error,
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures)}


def signed_in(who: str) -> Any:
    import requests

    from backend.services.demo_users import DEMO_PASSWORD

    client = requests.Session()
    client.post(f"{API}/api/v1/auth/login", timeout=30,
                json={"username": who, "password": DEMO_PASSWORD}
                ).raise_for_status()
    return client


def inbox(client: Any, code: str) -> list[dict[str, Any]]:
    """The messages about THIS project in somebody's own notifications."""
    rows = client.get(f"{API}/api/v1/workspace/notifications", timeout=60,
                      params={"limit": 100}).json().get("notifications", [])
    return [row for row in rows
            if code in f"{row.get('title', '')} {row.get('body', '')}"]


def sweep(client: Any, project_id: int) -> dict[str, Any]:
    out = client.post(f"{API}/api/v1/planner/projects/{project_id}/sweep",
                      timeout=180)
    out.raise_for_status()
    return out.json()


def run(report: Report, project_id: int, manager: str, owner: str,
        contact: str) -> Report:
    boss = signed_in(manager)
    detail = boss.get(f"{API}/api/v1/planner/projects/{project_id}",
                      timeout=60).json()
    project = detail["project"]
    code = project["code"]
    tasks = detail["tasks"]
    report.check("the project is readable and has work in it",
                 bool(tasks), f"{code}: {len(tasks)} task(s)")
    if not tasks:
        report.error = "nothing to chase"
        return report

    who = signed_in(owner)
    # A task nobody has been chased about yet, so that "a message arrived"
    # means this run produced it. The agent deliberately does not send the
    # same reminder twice, which would otherwise make a second run of this
    # script look like a failure.
    already = " ".join(f"{m.get('title')} {m.get('body')}"
                       for m in inbox(who, code))
    fresh = [t for t in tasks if t["code"] not in already]
    report.check("there is work the agent has not already chased",
                 bool(fresh),
                 f"{len(fresh)} of {len(tasks)} task(s) not yet chased")
    if not fresh:
        report.error = ("every task on this project has already been chased; "
                        "run this against a newly created project")
        return report
    target = fresh[0]
    before = len(inbox(who, code))

    # ---------------------------------------------- §26 a real chase, once
    # Both dates move together: the product refuses a due date before the
    # task's own start, which is right, so a manager moving a deadline
    # backwards moves the start with it.
    moved = boss.patch(f"{API}/api/v1/planner/tasks/{target['id']}",
                       timeout=60,
                       json={"start_date": (TODAY - timedelta(days=30)
                                            ).isoformat(),
                             "due_date": (TODAY - timedelta(days=9)
                                          ).isoformat(),
                             "version": target["version"]})
    report.check("a project manager can move a task's date",
                 moved.status_code == 200,
                 f"HTTP {moved.status_code} {moved.text[:120]}")

    first = sweep(boss, project_id)
    report.check("the agent ran and said what it did", "sent" in first,
                 json.dumps({k: first.get(k) for k in
                             ("projects", "tasks", "sent", "suppressed")}))

    said = inbox(who, code)
    report.check("the task owner was told, in their own inbox",
                 len(said) > before, f"{len(said)} message(s) about {code}")
    if said:
        text = " ".join(f"{m.get('title')} {m.get('body')}" for m in said)
        for wanted, why in (
                (code, "names the project"),
                (target["code"], "names the item"),
                ((TODAY - timedelta(days=9)).isoformat(), "gives the due date"),
                ("overdue", "says why it is being chased"),
                (f"/delivery/{project_id}", "carries a link back to it")):
            report.check(f"the message {why}", wanted in text,
                         "" if wanted in text else f"{wanted!r} is missing")

    # ------------------------------------------------- §26 and not twice
    again = sweep(boss, project_id)
    after = inbox(who, code)
    report.check("running the agent again does not send it twice",
                 len(after) == len(said),
                 f"{len(said)} before, {len(after)} after; "
                 f"{again.get('suppressed')} suppressed")

    # ---------------------------------------- §30 the activity trail says so
    trail = boss.get(
        f"{API}/api/v1/planner/projects/{project_id}/agent-activity",
        timeout=60)
    if trail.status_code == 200:
        events = trail.json().get("items", [])
        report.check("Agent activity records the chase", bool(events),
                     f"{len(events)} event(s)")
    else:
        report.check("Agent activity is readable",
                     trail.status_code == 200, f"HTTP {trail.status_code}")

    # ------------------------------------------- §27 the ladder, one rung up
    contact_client = signed_in(contact)
    had = len(inbox(contact_client, code))
    boss.patch(f"{API}/api/v1/planner/tasks/{target['id']}", timeout=60,
               json={"start_date": (TODAY - timedelta(days=90)).isoformat(),
                     "due_date": (TODAY - timedelta(days=45)).isoformat(),
                     "version": target["version"] + 1})
    sweep(boss, project_id)
    now = inbox(contact_client, code)
    report.check("a delay nobody resolved reached the escalation contact",
                 len(now) > had,
                 f"{len(now)} message(s) for {contact}, was {had}")
    if now:
        text = " ".join(f"{m.get('title')} {m.get('body')}" for m in now)
        report.check("the escalation says why it reached THEM",
                     "because" in text.lower(),
                     text[:200].replace("\n", " ⏎ "))

    # -------------------------------------- §29 and nobody else was told
    stranger = signed_in("layla.haddad")
    report.check("somebody not on the project was not told about it",
                 not inbox(stranger, code),
                 f"{len(inbox(stranger, code))} leaked")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--manager", default="priya.raman")
    ap.add_argument("--owner", default="priya.raman")
    ap.add_argument("--contact", default="amina.hassan")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"The agent, on project {args.project}\n")
    report = Report()
    try:
        run(report, args.project, args.manager, args.owner, args.contact)
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
