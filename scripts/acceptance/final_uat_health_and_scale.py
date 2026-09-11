#!/usr/bin/env python
"""What "health" means, how fast it arrives, and what the product admits.

§31, §48 and §49 of the final UAT.

  * **§31** health is *calculated* from the project's own rows and says
    why in a sentence. A project with nothing late is green. Make
    something late and it stops being green. A person who overrides it
    is named, and their reason is kept and shown — and clearing the
    override gives the calculation back rather than freezing it.
  * **§48** the screens a person opens every morning answer in a time
    they would not think about. Measured on the largest project this
    deployment actually holds, not on a two-task fixture.
  * **§49** the product says what its AI is, truthfully. If no provider
    key is configured it has to say so rather than imply a model is
    answering — and the Project Planner's own behaviour has to keep
    working without one, because the schedule rules are arithmetic.

    python -m scripts.acceptance.final_uat_health_and_scale --project 2970
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

API = os.environ.get("CREDITPROBE_API", "http://localhost:8000").rstrip("/")
TODAY = date.today()

#: What a person would put up with without noticing, per screen. Generous
#: on purpose: this is a "the product is not broken" line, not a target.
BUDGET_SECONDS = {
    "the portfolio": 4.0,
    "what needs somebody": 5.0,
    "one whole project": 4.0,
    "my own work": 4.0,
}


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


def detail(client: Any, project_id: int) -> dict[str, Any]:
    out = client.get(f"{API}/api/v1/planner/projects/{project_id}", timeout=90)
    out.raise_for_status()
    return out.json()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _recalculate(client: Any, project_id: int) -> dict[str, Any]:
    out = client.post(
        f"{API}/api/v1/planner/projects/{project_id}/recalculate", timeout=120)
    out.raise_for_status()
    return out.json()


# --------------------------------------------------------- §31 health

def _health(report: Report, boss: Any, project_id: int) -> None:
    before = detail(boss, project_id)
    tasks = before["tasks"]
    report.check("the project has work to judge it by", bool(tasks),
                 f"{len(tasks)} task(s)")
    if not tasks:
        return

    # "Nothing late" has to mean nothing at all outstanding, including an
    # open high risk — which counts towards health, correctly, and which
    # an earlier version of this scenario forgot to clear and then blamed
    # the product for.
    for item in before.get("raid", []):
        if str(item.get("status", "")).upper() not in ("CLOSED", "RESOLVED"):
            boss.patch(f"{API}/api/v1/planner/raid/{item['id']}", timeout=60,
                       json={"status": "CLOSED",
                             "resolution": "Closed for the health scenario."})

    # Put everything in the future and finish nothing: nothing is late.
    # `blocked: False` rather than an empty reason — the flag is what
    # leads here, and clearing only the reason on a task that is still
    # flagged is (rightly) refused as "a blocked task needs a reason".
    for n, task in enumerate(tasks):
        moved = boss.patch(
            f"{API}/api/v1/planner/tasks/{task['id']}", timeout=60,
            json={"blocked": False, "percent_complete": 20,
                  "start_date": day(5 + n), "due_date": day(60 + n),
                  "expected_version": task["version"]})
        report.check(f"{task['code']} could be reset for the scenario",
                     moved.status_code == 200,
                     f"HTTP {moved.status_code} {moved.text[:140]}")
    _recalculate(boss, project_id)
    calm = detail(boss, project_id)["project"]
    report.check("a project with nothing late is green",
                 str(calm.get("calculated_health")) == "GREEN",
                 f"{calm.get('calculated_health')}: "
                 f"{calm.get('health_reason')}")
    report.check("and says why in a sentence, not a code",
                 len(str(calm.get("health_reason") or "")) > 20
                 and " " in str(calm.get("health_reason") or ""),
                 str(calm.get("health_reason"))[:140])

    # Now make one thing genuinely late.
    late = detail(boss, project_id)["tasks"][0]
    boss.patch(f"{API}/api/v1/planner/tasks/{late['id']}", timeout=60,
               json={"start_date": day(-40), "due_date": day(-20),
                     "expected_version": late["version"]})
    _recalculate(boss, project_id)
    hurt = detail(boss, project_id)["project"]
    report.check("something twenty days overdue stops it being green",
                 str(hurt.get("calculated_health")) != "GREEN",
                 f"{hurt.get('calculated_health')}: "
                 f"{hurt.get('health_reason')}")
    report.check("and the reason names what is wrong",
                 "overdue" in str(hurt.get("health_reason") or "").lower(),
                 str(hurt.get("health_reason"))[:160])

    # A person disagreeing with the calculation.
    said = ("The vendor confirmed the extract for Friday, so the delay is "
            "contained and the end date has not moved.")
    over = boss.post(f"{API}/api/v1/planner/projects/{project_id}/health",
                     timeout=60, json={"health": "AMBER", "reason": said})
    report.check("a person can overrule the calculation",
                 over.status_code in (200, 201),
                 f"HTTP {over.status_code} {over.text[:140]}")

    now = detail(boss, project_id)["project"]
    report.check("the override is what the project now shows",
                 str(now.get("health")) == "AMBER", str(now.get("health")))
    report.check("their reason is kept, in their words",
                 "vendor confirmed" in json.dumps(now).lower(),
                 json.dumps({k: now.get(k) for k in
                             ("health", "manual_health", "health_reason",
                              "manual_health_reason")})[:240])
    report.check("and the person who said so is named",
                 bool(now.get("manual_health_by")
                      or now.get("manual_health_by_name")),
                 json.dumps({k: now.get(k) for k in now
                             if "manual" in k})[:200])
    report.check("the calculation is still there underneath, not overwritten",
                 str(now.get("calculated_health")) != "GREEN",
                 f"calculated {now.get('calculated_health')}, "
                 f"shown {now.get('health')}")

    cleared = boss.post(f"{API}/api/v1/planner/projects/{project_id}/health",
                        timeout=60, json={"health": "", "reason": ""})
    report.check("the override can be lifted", cleared.status_code in (200,
                                                                      201),
                 f"HTTP {cleared.status_code} {cleared.text[:140]}")
    back = detail(boss, project_id)["project"]
    report.check("and the calculation comes back rather than freezing",
                 str(back.get("health")) == str(back.get("calculated_health")),
                 f"shown {back.get('health')}, "
                 f"calculated {back.get('calculated_health')}")


# ---------------------------------------------------------- §48 scale

def _scale(report: Report, boss: Any) -> None:
    portfolio = boss.get(f"{API}/api/v1/planner/projects", timeout=120).json()
    rows = portfolio.get("projects", [])
    report.check("this deployment has enough projects to be worth timing",
                 len(rows) >= 5, f"{len(rows)} project(s)")

    # The largest project here, not a fixture: timing a two-task plan
    # proves the request works, not that the product scales.
    sizes = []
    for row in rows:
        try:
            sizes.append((len(detail(boss, int(row["id"])).get("tasks", [])),
                          int(row["id"]), str(row.get("code"))))
        except Exception:  # noqa: BLE001
            continue
    sizes.sort(reverse=True)
    biggest = sizes[0] if sizes else (0, 0, "")
    report.check("there is a project big enough to be a real test",
                 biggest[0] >= 20,
                 f"{biggest[2]} with {biggest[0]} tasks")

    def timed(name: str, call: Any) -> None:
        started = time.monotonic()
        out = call()
        took = time.monotonic() - started
        budget = BUDGET_SECONDS[name]
        report.check(f"{name} answers in under {budget:g}s",
                     out.status_code == 200 and took < budget,
                     f"HTTP {out.status_code} in {took:.2f}s")

    timed("the portfolio",
          lambda: boss.get(f"{API}/api/v1/planner/projects", timeout=120))
    timed("what needs somebody",
          lambda: boss.get(f"{API}/api/v1/planner/needs-attention",
                           params={"limit": 25}, timeout=120))
    timed("one whole project",
          lambda: boss.get(f"{API}/api/v1/planner/projects/{biggest[1]}",
                           timeout=120))
    timed("my own work",
          lambda: boss.get(f"{API}/api/v1/planner/my-work", timeout=120))

    # And the list a person reads first has to be bounded, however big the
    # estate gets — a screen that grows without limit is a screen nobody
    # reads twice.
    attention = boss.get(f"{API}/api/v1/planner/needs-attention",
                         params={"limit": 25}, timeout=120).json()
    items = attention.get("items", [])
    report.check("the attention list respects the limit it was given",
                 len(items) <= 25, f"{len(items)} item(s) for a limit of 25")
    # The row carries the whole project under "project"; reading a flat
    # `project_code` gives None for every row, which would have made this
    # fail on a product that is doing the right thing.
    nameless = [r for r in items
                if not (r.get("project") or {}).get("code")]
    report.check("and every row on it says which project it belongs to",
                 not nameless,
                 f"{len(nameless)} row(s) with no project named"
                 if nameless else
                 f"all {len(items)} name theirs, e.g. "
                 f"{(items[0].get('project') or {}).get('code')}"
                 if items else "no rows")
    report.check("and every row says what it wants done, in a sentence",
                 all(len(str(r.get("reason") or "")) > 15 for r in items),
                 str((items[0] if items else {}).get("reason"))[:120])


# ------------------------------------------------- §49 what it admits

def _honesty(report: Report, boss: Any, project_id: int) -> None:
    health = boss.get(f"{API}/api/v1/health", timeout=60).json()
    parts = {c["name"]: c for c in health.get("components", [])}
    ai = parts.get("ai_provider", {})
    report.check("the product reports the state of its AI provider",
                 bool(ai), json.dumps(ai)[:200])
    configured = str(ai.get("status")) not in ("not_configured", "offline")
    report.check("and says plainly which state it is in",
                 len(str(ai.get("detail") or "")) > 20,
                 f"{ai.get('status')}: {str(ai.get('detail'))[:140]}")

    if not configured:
        report.check("LIVE AI — NOT VERIFIED: no provider key is configured "
                     "on this deployment, so nothing here claims a model "
                     "answered anything", True,
                     str(ai.get("detail"))[:200])
        # The claim that matters: the Planner's own judgement is
        # arithmetic, so it must be unaffected by the absence of a model.
        swept = boss.post(
            f"{API}/api/v1/planner/projects/{project_id}/sweep", timeout=180)
        report.check("the agent still watches, detects and reminds without "
                     "a model behind it", swept.status_code == 200,
                     json.dumps(swept.json())[:200]
                     if swept.status_code == 200
                     else f"HTTP {swept.status_code}")
        shown = detail(boss, project_id)["project"]
        report.check("and health is still calculated without one",
                     bool(shown.get("calculated_health")),
                     f"{shown.get('calculated_health')}: "
                     f"{str(shown.get('health_reason'))[:100]}")
    else:
        report.check("a provider is configured, so live AI can be verified "
                     "separately", True, str(ai.get("detail"))[:200])


def run(report: Report, *, who: str, project_id: int) -> Report:
    boss = signed_in(who)
    print("\n§31 — what health means")
    _health(report, boss, project_id)
    print("\n§48 — how fast it arrives")
    _scale(report, boss)
    print("\n§49 — what the product admits about its AI")
    _honesty(report, boss, project_id)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", default="priya.raman")
    ap.add_argument("--project", type=int, required=True)
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    print(f"Health, scale and honesty, on project {args.project}")
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
