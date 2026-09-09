#!/usr/bin/env python
"""The agentic demonstration, run as arithmetic rather than as a story.

    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py
    .venv/bin/python scripts/acceptance/agentic_demo_scenario.py --json

§43 asks for a demonstration somebody can run in front of a client and get
the same answer every time. That rules out "open the screen and see what the
agent noticed", because what it noticed depends on when the demo database was
built. So this drives the REAL sweep at a frozen date over the seeded Retail
Application Scorecard Redevelopment, and asserts the exact set of people told
the exact set of things.

The scenario, which is the same one the programme is built to tell:

    S-507  Segment performance analysis is four days overdue. Rohan owns it
           and has said nothing. Under CRITICAL the agent reminds him, tells
           the milestone's escalation contact, and — because four days is
           past the sponsor threshold — tells the sponsor too.

    S-705  The reject inference extract is blocked on the decision engine
           team. Chasing Daniel produces nothing; the escalation contact is
           the person who can go and get it.

    S-702  Independent replication is due in two days at 40%. A reminder, not
           an escalation: there is still time.

    S-703  Sensitivity and limitations has had no update at all. Silence is
           a different fact from lateness and gets its own nudge.

Then it runs the sweep a second time and asserts that NOTHING new is sent,
which is the property a client asks about within about ninety seconds of
seeing the first screen.

It FAILS rather than skips when the demo is not seeded. "The programme was
missing so we skipped the demonstration" is the report that lets an empty
demo reach a client.
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CODE = os.environ.get("PLANNER_DEMO_CODE", "RET-SCORECARD")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"check": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class Report:
    steps: list[Step] = field(default_factory=list)
    error: str = ""
    observed: dict[str, Any] = field(default_factory=dict)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps.append(Step(name, bool(ok), detail))
        return bool(ok)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [s.to_dict() for s in self.steps],
                "passed": len(self.steps) - len(self.failures),
                "failed": len(self.failures), "error": self.error,
                "observed": self.observed}


def run(report: Report) -> Report:
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.planner import (
        PlannerMilestone,
        PlannerProject,
        PlannerReminder,
    )
    from backend.planner import control, monitor
    from backend.planner import escalation as esc
    from backend.planner import policy as pol
    from backend.planner import query as pq

    with get_session() as session:
        project = session.execute(select(PlannerProject).where(
            PlannerProject.code == CODE)).scalar_one_or_none()
        if project is None:
            report.error = (
                f"{CODE} is not in this database. Run "
                "scripts/seed_retail_portfolio.py. The demonstration did NOT "
                "run and is NOT passed.")
            return report
        pid = int(project.id)

        # ---- the plan is set up the way the demonstration needs it
        report.check("the programme is monitored on Critical",
                     project.agentic_mode == pol.MODE_CRITICAL,
                     f"mode is {project.agentic_mode}")
        report.check("the programme has an escalation contact",
                     bool(project.escalation_id))

        stones = session.execute(select(PlannerMilestone).where(
            PlannerMilestone.project_id == pid)).scalars().all()
        report.check("every milestone names who hears about a slip",
                     all(m.escalation_id for m in stones),
                     f"{sum(1 for m in stones if m.escalation_id)}"
                     f"/{len(stones)}")

        today = date.today()
        plan = pq.plans_of(session, [pid])[pid]
        rules = pol.of(project).policy
        states: dict[str, list[str]] = {"overdue": [], "blocked": [],
                                        "stale": [], "imminent": []}
        for task in plan.tasks:
            if not task.open:
                continue
            if control.days_overdue(task, today):
                states["overdue"].append(task.code)
            elif task.blocked:
                states["blocked"].append(task.code)
            elif (near := control.days_until_due(task, today)) is not None \
                    and near <= 3:
                states["imminent"].append(task.code)
            elif control.is_stale(task, today, policy=rules,
                                  window=plan.stale_after_days):
                states["stale"].append(task.code)
        report.observed["states"] = states

        # §30 names four states, and a demonstration missing one of them
        # cannot show the agent doing the thing it exists to do.
        for state in ("overdue", "blocked", "stale", "imminent"):
            report.check(f"the programme has something {state}",
                         bool(states[state]), f"{states[state]}")
        report.check("the overdue item is the segment analysis",
                     "S-507" in states["overdue"], f"{states['overdue']}")
        report.check("the blocked item is the reject inference extract",
                     "S-705" in states["blocked"], f"{states['blocked']}")
        report.check("the imminent item is the independent replication",
                     "S-702" in states["imminent"], f"{states['imminent']}")

        # ---- the first sweep
        monitor.sweep(session, today=today, project_ids=[pid])
        session.commit()

    with get_session() as session:
        rows = list(session.execute(select(PlannerReminder).where(
            PlannerReminder.project_id == pid)).scalars())
    first = len(rows)
    by_trigger: dict[str, list[str]] = {}
    for row in rows:
        by_trigger.setdefault(row.trigger, []).append(row.entity_id and "")
    report.observed["by_trigger"] = {k: len(v) for k, v in by_trigger.items()}

    sent = {(r.trigger, r.entity_id) for r in rows}
    codes = {int(t.id): t.code for t in plan.tasks}

    def told(trigger: str) -> set[str]:
        return {codes.get(int(e), str(e)) for t, e in sent if t == trigger}

    report.check("the owner is reminded the segment analysis is overdue",
                 "S-507" in told(monitor.OVERDUE), f"{told(monitor.OVERDUE)}")
    report.check("the owner is told the extract is blocked",
                 "S-705" in told(monitor.BLOCKED), f"{told(monitor.BLOCKED)}")
    report.check("the replication is reminded about, not escalated",
                 "S-702" in told(monitor.DUE)
                 and "S-702" not in told(esc.ESCALATED),
                 f"due={told(monitor.DUE)} escalated={told(esc.ESCALATED)}")
    report.check("the overdue item is escalated above its owner",
                 "S-507" in told(esc.ESCALATED), f"{told(esc.ESCALATED)}")
    report.check("the blocked item is escalated above its owner",
                 "S-705" in told(esc.ESCALATED_BLOCKED),
                 f"{told(esc.ESCALATED_BLOCKED)}")
    report.check("the sponsor hears about the four-day delay",
                 "S-507" in told(esc.SPONSOR_ALERT),
                 f"{told(esc.SPONSOR_ALERT)}")

    # Nobody is told twice about one thing, however many rungs they occupy.
    pairs = [(r.entity_type, r.entity_id, r.user_id) for r in rows]
    report.check("nobody is told twice about the same thing",
                 len(pairs) == len(set(pairs)),
                 f"{len(pairs)} messages, {len(set(pairs))} distinct")

    # An escalation that does not say why it reached this person gets filed.
    escalations = [r for r in rows if r.trigger in esc.TRIGGERS]
    report.check("every escalation names a recipient", 
                 all(r.user_id for r in escalations))

    # ---- the second sweep, which is the whole point
    with get_session() as session:
        monitor.sweep(session, today=date.today(), project_ids=[pid])
        session.commit()
    with get_session() as session:
        again = len(list(session.execute(select(PlannerReminder).where(
            PlannerReminder.project_id == pid)).scalars()))
    report.observed["messages"] = {"first_sweep": first,
                                   "after_second": again}
    report.check("running the agent again sends nothing new",
                 again == first, f"{first} then {again}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = Report()
    try:
        run(report)
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        report.error = f"{type(exc).__name__}: {exc}"

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for step in report.steps:
            mark = "PASS" if step.ok else "FAIL"
            print(f"[{mark}] {step.name}"
                  + (f" — {step.detail}" if step.detail and not step.ok
                     else ""))
        print(f"\n{len(report.steps) - len(report.failures)} passed, "
              f"{len(report.failures)} failed")
        if report.observed:
            print(f"\nobserved: {json.dumps(report.observed)}")
        if report.error:
            print(f"\n{report.error}")
    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_FAILED if report.failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
