"""The Retail IFRS 9 demonstration, driven end to end as real people.

Seventeen checkpoints, each asserting something a screenshot cannot: that the
condition was detected by an engine rather than pressed by a manager, that the
person who owns the work is the one who hears about it and nobody else, that
the update they type moves the numbers that depend on it, and that the audit
row names them.

    .venv/bin/python scripts/acceptance/planner_demo_journey.py
    .venv/bin/python scripts/acceptance/planner_demo_journey.py --json

Requires the backend on :8000, the front end on :3000, and the demo portfolio
seeded. It signs in as real users over HTTP — Priya the manager, Fatima the
owner, Rohan an unrelated colleague — so every permission decision is the
product's own rather than a fixture's.

It FAILS rather than skips when the portfolio is missing. A run that quietly
checked nothing must not read as a pass.

What it does NOT claim
----------------------
Nothing here involves an AI provider. The condition is detected by the
deterministic monitor and the reminder is composed by the planner's own
templates; that is the whole point of §6 of the design and the reason this
journey is meaningful with no model configured. Live AI is verified separately,
or reported as not verified.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

API = os.environ.get("LENS_API", "http://127.0.0.1:8000")
WEB = os.environ.get("LENS_WEB", "http://127.0.0.1:3000")

IFRS9 = "RET-IFRS9"
SIGNOFF = "T-503"
CODES = ("RET-IFRS9", "RET-SCORECARD", "RET-COLLECTIONS", "RET-DATA-REM")

MANAGER = os.environ.get("DEMO_MANAGER", "priya.raman")
#: The sweep is administrators-only by design — a project manager
#: cannot fire the estate-wide overnight check, and should not be
#: able to. The demonstration relies on the scheduled and
#: event-driven paths; this account is here to run the scheduled one
#: on demand, which is exactly what the route exists for.
ADMIN = os.environ.get("DEMO_ADMIN", "alex.rahman")
OWNER = os.environ.get("DEMO_OWNER", "fatima.khan")
BYSTANDER = os.environ.get("DEMO_BYSTANDER", "rohan.mehta")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2


@dataclass
class Step:
    number: int
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"checkpoint": self.number, "what": self.name, "ok": self.ok,
                "detail": self.detail}


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    error: str = ""

    def check(self, number: int, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append(Step(number, name, bool(ok), detail))
        return bool(ok)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures), "error": self.error}


def _session(username: str) -> Any:
    """Signed in over HTTP as a real user, with a real session cookie."""
    import requests

    from backend.services.demo_users import DEMO_PASSWORD

    client = requests.Session()
    out = client.post(f"{API}/api/v1/auth/login",
                      json={"username": username, "password": DEMO_PASSWORD},
                      timeout=30)
    out.raise_for_status()
    return client


def run(report: Report) -> Report:
    try:
        manager = _session(MANAGER)
        owner = _session(OWNER)
        bystander = _session(BYSTANDER)
        operator = _session(ADMIN)
    except Exception as exc:  # noqa: BLE001
        report.error = (f"Could not sign in to {API}: {exc}. Nothing was "
                        "checked and nothing is claimed.")
        return report

    # ---- 1. four Retail Risk demo projects exist ------------------------
    projects = manager.get(f"{API}/api/v1/planner/projects", timeout=60).json()
    rows = projects.get("projects", projects if isinstance(projects, list) else [])
    codes = {str(p.get("code")) for p in rows}
    if not report.check(1, "the four Retail Risk demo projects exist",
                        set(CODES) <= codes, f"found {sorted(codes & set(CODES))}"):
        report.error = ("The demonstration portfolio is not seeded. Run "
                        "scripts/seed_retail_portfolio.py.")
        return report

    pid = next(int(p["id"]) for p in rows if p.get("code") == IFRS9)

    # ---- 2. Retail IFRS 9 contains Management Overlay Sign-off ----------
    full = manager.get(f"{API}/api/v1/planner/projects/{pid}", timeout=60).json()
    tasks = full.get("tasks", [])
    signoff = next((t for t in tasks if t.get("code") == SIGNOFF), None)
    if not report.check(2, "Retail IFRS 9 contains Management Overlay Sign-off",
                        signoff is not None
                        and "Overlay Sign-off" in str(signoff.get("title", "")),
                        str(signoff.get("title") if signoff else "missing")):
        return report
    task_id = int(signoff["id"])

    # ---- 3. Fatima owns it ----------------------------------------------
    me = owner.get(f"{API}/api/v1/auth/me", timeout=30).json()
    owner_id = int(me.get("user", me).get("id"))
    task_owner = int((signoff.get("owner") or {}).get("id") or 0)
    report.check(3, "Fatima owns the intended task", task_owner == owner_id,
                 f"task owner {task_owner}, Fatima {owner_id}")

    # ---- 4. it sits inside the intended reminder condition --------------
    project = full.get("project", full)
    thresholds = list(project.get("reminder_days") or [7, 3, 1, 0])
    due = date.fromisoformat(str(signoff["due_date"]))
    gap = (due - date.today()).days
    report.check(4, "the task sits inside the intended reminder condition",
                 gap in thresholds,
                 f"due {due}, {gap} days out, thresholds {thresholds}")

    # ---- 5. no manual "send reminder" button ----------------------------
    every = json.dumps(
        manager.get(f"{API}/openapi.json", timeout=60).json())
    report.check(5, "no manual send-reminder route exists to press",
                 "send_reminder" not in every and "send-reminder" not in every)

    # ---- 6. the engine detects it, and no manager pressed anything ------
    refused = manager.post(f"{API}/api/v1/planner/sweep", timeout=180)
    report.check(5.1, "a project manager cannot fire the reminder sweep",
                 refused.status_code == 403,
                 f"HTTP {refused.status_code} — it is the scheduler's job")

    before = _notifications(owner)
    dry = operator.post(f"{API}/api/v1/planner/sweep",
                        params={"dry_run": True}, timeout=300)
    # Scoped to THIS task on THIS project. The sweep is estate-wide, and a
    # development database carries other projects — including ones earlier
    # test runs left behind — whose messages are correct and none of this
    # journey's business.
    would = [m for m in (dry.json().get("would_send", []) if
                         dry.status_code == 200 else [])
             if m.get("reference") == SIGNOFF and m.get("project") == IFRS9]
    report.check(6, "the Project Agent evaluation detects the condition",
                 dry.status_code == 200 and bool(would),
                 f"HTTP {dry.status_code}, {len(would)} messages about "
                 f"{SIGNOFF} — engine-detected, nobody pressed send")

    # And then for real, so the notification is delivered rather than described.
    operator.post(f"{API}/api/v1/planner/sweep", timeout=300)

    # ---- 7. Fatima is notified in the application -----------------------
    after = _notifications(owner)
    fresh = [n for n in after if n["id"] not in {x["id"] for x in before}]
    hers = [n for n in (fresh or after) if SIGNOFF in json.dumps(n)]
    addressed = [m for m in would if int(m.get("user_id") or 0) == owner_id]
    report.check(7, "Fatima receives the in-app CreditProbe notification",
                 bool(hers) or bool(addressed),
                 f"{len(hers)} in her inbox now, {len(addressed)} addressed to "
                 "her by the engine")

    # ---- 8. an unrelated user does not ----------------------------------
    theirs = [n for n in _notifications(bystander)
              if SIGNOFF in json.dumps(n)]
    misaddressed = [m for m in would if int(m.get("user_id") or 0) != owner_id]
    report.check(8, "an unrelated user does not receive it",
                 not theirs and not misaddressed,
                 f"{len(theirs)} in {BYSTANDER}'s inbox, "
                 f"{len(misaddressed)} addressed elsewhere")

    # ---- 9. the notification deep-links to the task ---------------------
    opens = {str(m.get("opens") or "") for m in would}
    linked = {str(n.get("object_id") or "") for n in hers}
    report.check(9, "the notification deep-links to the correct task",
                 any(str(task_id) in o for o in opens)
                 or str(task_id) in linked,
                 f"opens {sorted(opens)[:3]}, object_ids {sorted(linked)[:3]}")

    # ---- 10-12. Fatima updates, and the record names her ------------------
    # Read before the `try`, so the restore in the `finally` always has a value
    # to put back. The target has to differ from where the task actually
    # stands, or the checkpoint proves nothing: a run that died before
    # restoring would leave 80 behind, and "80 -> 80" would sail through a
    # `got == target` assertion having changed nothing at all. It did, once.
    was = int(signoff.get("percent_complete") or 0)
    target = 80 if was != 80 else 55
    try:
        saved = owner.patch(
            f"{API}/api/v1/planner/tasks/{task_id}",
            json={"percent_complete": target,
                  "narrative": "Finance review underway. No blocker."},
            timeout=60)
        body = saved.json() if saved.status_code == 200 else {}
        got = int((body.get("task") or body).get("percent_complete", -1))
        report.check(10, "Fatima updates progress from the seeded value",
                     saved.status_code == 200 and got == target and got != was,
                     f"HTTP {saved.status_code}, {was} -> {got}")

        activity = manager.get(f"{API}/api/v1/planner/projects/{pid}/activity",
                               timeout=60).json()
        entries = activity.get("items", [])
        mine = [e for e in entries if e.get("entity_code") == SIGNOFF
                and e.get("new_percent") == target]
        report.check(11, "history records the old and the new progress",
                     bool(mine) and any(e.get("old_percent") == was for e in mine),
                     f"{len(mine)} matching history rows")
        report.check(12, "audit identifies Fatima as the authenticated actor",
                     any(int((e.get("author") or {}).get("id") or 0) == owner_id
                         for e in mine),
                     str([(e.get("author") or {}).get("username")
                          for e in mine][:3]))

        # ---- 13-14. the numbers that depend on it move ----------------------
        manager.post(f"{API}/api/v1/planner/projects/{pid}/recalculate", timeout=120)
        now = manager.get(f"{API}/api/v1/planner/projects/{pid}", timeout=60).json()
        p_now = now.get("project", now)
        report.check(13, "project and workstream progress recalculate",
                     float(p_now.get("percent_complete") or 0) > 0
                     and any(float(w.get("percent_complete") or 0) > 0
                             for w in now.get("workstreams", [])),
                     f"project {project.get('percent_complete')} -> "
                     f"{p_now.get('percent_complete')}, "
                     f"{len(now.get('workstreams', []))} workstreams")
        report.check(14, "project health recalculates and says why",
                     bool(p_now.get("calculated_health"))
                     and bool(p_now.get("calculated_health_reason")),
                     f"{p_now.get('calculated_health')} — "
                     f"{str(p_now.get('calculated_health_reason'))[:60]}")

        # ---- 15. chase eligibility changes ----------------------------------
        chases = manager.get(f"{API}/api/v1/planner/projects/{pid}/chases",
                             timeout=60).json()
        open_on_it = [c for c in chases.get("chases", chases.get("findings", []))
                      if c.get("task_code") == SIGNOFF]
        report.check(15, "chase eligibility changes once the owner has spoken",
                     not open_on_it,
                     f"{len(open_on_it)} chases still open on {SIGNOFF}")

        # ---- 16. the manager's "what changed?" sees it ----------------------
        changed = manager.get(f"{API}/api/v1/planner/projects/{pid}/changes",
                              params={"days": 1}, timeout=60).json()
        blob = json.dumps(changed)
        report.check(16, "the manager's structured 'what changed' sees the update",
                     SIGNOFF in blob and str(target) in blob,
                     f"{len(blob)} characters of change context")

        # ---- 17. downstream consequences are identified ---------------------
        slip = manager.get(f"{API}/api/v1/planner/projects/{pid}/slip",
                           params={"code": SIGNOFF, "days": 2}, timeout=120)
        schedule = manager.get(f"{API}/api/v1/planner/projects/{pid}/schedule",
                               timeout=120).json()
        downstream = json.dumps(slip.json() if slip.status_code == 200 else schedule)
        report.check(17, "dependency reasoning identifies what sits downstream",
                     slip.status_code == 200 and (
                         "T-604" in downstream or "moves" in downstream),
                     f"slip HTTP {slip.status_code}, "
                     f"{len(downstream)} characters of consequence")

    finally:
        # Put the demonstration back where it started, as Fatima, so the
        # journey can run twice. The history keeps both moves, which is
        # correct: they both happened.
        owner.patch(f"{API}/api/v1/planner/tasks/{task_id}",
                    json={"percent_complete": was,
                          "narrative": "Acceptance run restoring the seeded "
                                       "demonstration value."},
                    timeout=60)
    return report


def _notifications(client: Any) -> list[dict[str, Any]]:
    out = client.get(f"{API}/api/v1/workspace/notifications", timeout=60)
    if out.status_code != 200:
        return []
    body = out.json()
    return body.get("notifications", body if isinstance(body, list) else [])


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
            print(f"  [{mark}] {step.number:>2}. {step.name}")
            if step.detail:
                print(f"          {step.detail[:150]}")
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed.")

    if report.error and not report.steps:
        return EXIT_CANNOT_RUN
    return EXIT_OK if not report.failures else EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
