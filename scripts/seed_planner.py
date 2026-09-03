#!/usr/bin/env python
"""One realistic delivery plan: the IFRS 9 model redevelopment.

    python scripts/seed_planner.py            build it if it is not there
    python scripts/seed_planner.py --check    report only; change nothing
    python scripts/seed_planner.py --force    rebuild it
    python scripts/seed_planner.py --json     machine-readable result

Why this shape
--------------
A project planner shown with three tidy tasks proves nothing. What a senior
risk person needs to see before trusting one is a plan with the awkward parts
in it: work that is late, work that is stuck behind somebody else, a decision
nobody has made, a risk with a name on it, and a history that shows the plan
changing rather than a snapshot that was always this way.

So this seeds one project with six workstreams, twenty-four tasks including
subtasks, five milestones, real dependencies, and — deliberately — one task
overdue, one blocked with a reason, one completed, one high risk open, one
decision outstanding, and a fortnight of status updates behind them.

Dates are anchored to TODAY rather than written as constants, so the plan is
still overdue-in-the-right-places six months from now.

What it will not do
-------------------
It writes only through `backend.planner.service`, with SOURCE=UI and a named
author, so every row it creates is subject to the same validation and lands in
the same history as a row a person would have typed. A seed that inserted
directly would be able to create states the product cannot, which is how a
demonstration ends up showing something that cannot happen.

It is idempotent on the project code and touches nothing else. `--force`
removes the project it previously built and no other.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_CODE = "IFRS9-REDEV"

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_CANNOT_RUN = 2

#: The people the plan needs. Matched on username; created only if absent, and
#: never given a usable password — these are figures in a plan, not accounts.
CAST = [
    ("amina.hassan", "Amina", "Hassan", "ANALYST",
     "Head of Credit Risk Analytics"),
    ("daniel.okafor", "Daniel", "Okafor", "ANALYST", "Senior Model Developer"),
    ("priya.raman", "Priya", "Raman", "ANALYST", "IFRS 9 Manager"),
    ("tom.whitfield", "Tom", "Whitfield", "ANALYST", "Data Engineer"),
    ("lena.brandt", "Lena", "Brandt", "VIEWER", "Model Validation"),
    ("samir.khoury", "Samir", "Khoury", "ANALYST", "Finance Business Partner"),
]


class Seeder:
    """Just enough of a principal to satisfy the service layer."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, _allowed: Any) -> bool:
        return True


@dataclass
class Report:
    built: bool = False
    project_id: int | None = None
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"built": self.built, "project_id": self.project_id,
                "project_code": PROJECT_CODE, "counts": dict(self.counts),
                "notes": list(self.notes), "error": self.error}


def _people(session: Any) -> dict[str, int]:
    from sqlalchemy import select

    from backend.db.models import User

    found: dict[str, int] = {}
    for username, first, last, role, title in CAST:
        existing = session.execute(
            select(User).where(User.username == username)).scalar_one_or_none()
        if existing is None:
            existing = User(username=username, password_hash="!",
                            role=role, first_name=first, last_name=last,
                            email=f"{username}@example.invalid",
                            job_title=title, department="Risk",
                            team="IFRS 9 Redevelopment", is_active=True)
            session.add(existing)
            session.flush()
        found[username] = int(existing.id)
    return found


def plan(today: date) -> dict[str, Any]:
    """The whole plan as data, relative to a day.

    Written as one structure rather than a hundred service calls so the shape
    is reviewable: somebody checking that the seed contains an overdue task
    and an unmade decision can see both without reading imperative code.
    """
    def d(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    return {
        "project": {
            "code": PROJECT_CODE,
            "name": "IFRS 9 Model Redevelopment",
            "status": "ACTIVE", "priority": "HIGH",
            "objective": "Rebuild the corporate PD, LGD and EAD models on the "
                         "post-2023 data, and have the redeveloped ECL "
                         "approved by the Model Committee before year end.",
            "business_context": "The current corporate PD model was "
                                "calibrated on a pre-pandemic window and has "
                                "been failing its annual back-test on the "
                                "shipping and real-estate books for two "
                                "cycles. Validation has raised it as a "
                                "high-severity finding.",
            "start_date": d(-120), "target_end_date": d(140),
            "reporting_cadence": "WEEKLY", "stale_after_days": 7,
        },
        "participants": [
            ("amina.hassan", "SPONSOR", "OWNER"),
            ("priya.raman", "PROJECT_MANAGER", "OWNER"),
            ("daniel.okafor", "WORKSTREAM_LEAD", "EDITOR"),
            ("tom.whitfield", "WORKSTREAM_LEAD", "EDITOR"),
            ("samir.khoury", "CONTRIBUTOR", "CONTRIBUTOR"),
            ("lena.brandt", "REVIEWER", "VIEWER"),
        ],
        "workstreams": [
            ("WS-DATA", "Data foundation", "tom.whitfield", 1, -120, -40),
            ("WS-PD", "PD redevelopment", "daniel.okafor", 2, -70, 40),
            ("WS-LGD", "LGD and EAD", "daniel.okafor", 3, -40, 70),
            ("WS-ECL", "ECL engine and staging", "priya.raman", 4, 0, 100),
            ("WS-VAL", "Validation and approval", "lena.brandt", 5, 60, 130),
            ("WS-IMPL", "Implementation and parallel run",
             "tom.whitfield", 6, 90, 140),
        ],
        "tasks": [
            # code, title, ws, parent, owner, status, %, start, due, weight,
            # critical, blocked, reason, next step
            ("T-101", "Assemble the corporate default history",
             "WS-DATA", None, "tom.whitfield", "COMPLETED", 100, -120, -95,
             3, True, False, "", ""),
            ("T-102", "Reconcile defaults to the finance ledger",
             "WS-DATA", None, "samir.khoury", "COMPLETED", 100, -100, -80,
             2, False, False, "", ""),
            ("T-103", "Build the macro-economic panel",
             "WS-DATA", None, "tom.whitfield", "COMPLETED", 100, -95, -70,
             2, False, False, "", ""),
            ("T-104", "Data quality sign-off",
             "WS-DATA", None, "lena.brandt", "COMPLETED", 100, -75, -55,
             1, False, False, "", ""),

            ("T-201", "Single-factor analysis on the corporate book",
             "WS-PD", None, "daniel.okafor", "COMPLETED", 100, -70, -50,
             2, False, False, "", ""),
            ("T-202", "Candidate PD model fitting",
             "WS-PD", None, "daniel.okafor", "IN_PROGRESS", 70, -50, 10,
             4, True, False, "",
             "Two candidates left; picking on Gini and stability."),
            ("T-202a", "Shipping sub-portfolio segmentation",
             "WS-PD", "T-202", "daniel.okafor", "IN_PROGRESS", 60, -40, 5,
             1, False, False, "", "Waiting on the vessel-age field."),
            ("T-202b", "Real-estate sub-portfolio segmentation",
             "WS-PD", "T-202", "daniel.okafor", "IN_PROGRESS", 45, -40, 8,
             1, False, False, "", ""),
            ("T-203", "PD calibration to the long-run average",
             "WS-PD", None, "priya.raman", "NOT_STARTED", 0, 10, 30,
             2, True, False, "", ""),
            ("T-204", "PD back-test pack",
             "WS-PD", None, "daniel.okafor", "NOT_STARTED", 0, 25, 45,
             2, False, False, "", ""),

            ("T-301", "LGD workout data extraction",
             "WS-LGD", None, "tom.whitfield", "IN_PROGRESS", 80, -40, -6,
             3, True, False, "",
             "Two recovery files still to load."),
            ("T-302", "Collateral haircut review",
             "WS-LGD", None, "samir.khoury", "BLOCKED", 20, -30, 12,
             2, False, True,
             "Waiting on the updated valuation policy from Credit Policy; "
             "chased 4 October, no date given.",
             "Escalate at the next steering committee."),
            ("T-303", "EAD / CCF estimation",
             "WS-LGD", None, "daniel.okafor", "NOT_STARTED", 0, 15, 50,
             2, False, False, "", ""),

            ("T-401", "ECL engine configuration",
             "WS-ECL", None, "priya.raman", "NOT_STARTED", 0, 30, 65,
             3, True, False, "", ""),
            ("T-402", "Staging criteria review",
             "WS-ECL", None, "priya.raman", "IN_PROGRESS", 30, -10, 20,
             2, False, False, "", "Drafting the SICR quantitative test."),
            ("T-403", "Forward-looking scenario weights",
             "WS-ECL", None, "amina.hassan", "NOT_STARTED", 0, 40, 70,
             2, False, False, "", ""),
            ("T-404", "Impact analysis versus current ECL",
             "WS-ECL", None, "samir.khoury", "NOT_STARTED", 0, 65, 85,
             3, True, False, "", ""),

            ("T-501", "Independent validation of the PD model",
             "WS-VAL", None, "lena.brandt", "NOT_STARTED", 0, 45, 80,
             3, True, False, "", ""),
            ("T-502", "Independent validation of LGD and EAD",
             "WS-VAL", None, "lena.brandt", "NOT_STARTED", 0, 60, 95,
             2, False, False, "", ""),
            ("T-503", "Model Committee submission pack",
             "WS-VAL", None, "priya.raman", "NOT_STARTED", 0, 95, 115,
             2, True, False, "", ""),

            ("T-601", "Production data pipeline build",
             "WS-IMPL", None, "tom.whitfield", "NOT_STARTED", 0, 90, 120,
             3, False, False, "", ""),
            ("T-602", "Parallel run against the current engine",
             "WS-IMPL", None, "tom.whitfield", "NOT_STARTED", 0, 115, 135,
             3, True, False, "", ""),
            ("T-603", "Finance sign-off on the parallel run",
             "WS-IMPL", None, "samir.khoury", "NOT_STARTED", 0, 130, 140,
             1, False, False, "", ""),
            ("T-604", "Decommission the old model",
             "WS-IMPL", None, "tom.whitfield", "NOT_STARTED", 0, 138, 145,
             1, False, False, "", ""),
        ],
        "milestones": [
            ("M-1", "Data foundation complete", "WS-DATA", "tom.whitfield",
             -55, "ACHIEVED", True),
            ("M-2", "PD model selected", "WS-PD", "daniel.okafor", 12,
             "PENDING", True),
            ("M-3", "Full ECL model built", "WS-ECL", "priya.raman", 70,
             "PENDING", True),
            ("M-4", "Validation opinion issued", "WS-VAL", "lena.brandt",
             100, "PENDING", True),
            ("M-5", "Model Committee approval", "WS-VAL", "amina.hassan",
             120, "PENDING", True),
        ],
        "dependencies": [
            ("TASK", "T-101", "TASK", "T-201", "FS", 0),
            ("TASK", "T-104", "TASK", "T-202", "FS", 0),
            ("TASK", "T-202", "TASK", "T-203", "FS", 0),
            ("TASK", "T-203", "TASK", "T-204", "FS", 0),
            ("TASK", "T-202", "MILESTONE", "M-2", "FS", 0),
            ("TASK", "T-301", "TASK", "T-302", "SS", 0),
            ("TASK", "T-302", "TASK", "T-303", "FS", 0),
            ("TASK", "T-203", "TASK", "T-401", "FS", 0),
            ("TASK", "T-303", "TASK", "T-401", "FS", 0),
            ("TASK", "T-401", "TASK", "T-404", "FS", 0),
            ("TASK", "T-401", "MILESTONE", "M-3", "FS", 0),
            ("TASK", "T-204", "TASK", "T-501", "FS", 0),
            ("TASK", "T-501", "TASK", "T-503", "FS", 0),
            ("TASK", "T-502", "TASK", "T-503", "FS", 0),
            ("TASK", "T-503", "MILESTONE", "M-5", "FS", 0),
            ("TASK", "T-404", "TASK", "T-601", "FS", 0),
            ("TASK", "T-601", "TASK", "T-602", "FS", 0),
            ("TASK", "T-602", "TASK", "T-603", "FS", 0),
        ],
        "raid": [
            ("RISK", "Key modeller unavailable from November",
             "Daniel is committed to the ICAAP submission from mid-November. "
             "Without cover, PD calibration and the back-test pack both slip.",
             "HIGH", "OPEN", "priya.raman", 30,
             "Agree a named deputy with Analytics before the end of the "
             "month; front-load the calibration work.", ""),
            ("RISK", "Workout recovery data is incomplete before 2019",
             "Two years of recovery cases were archived without the "
             "collateral realisation dates, which weakens the LGD sample.",
             "MEDIUM", "OPEN", "tom.whitfield", 20,
             "Use the shorter window and disclose the limitation in the "
             "validation pack.", ""),
            ("DECISION", "Which staging approach for the shipping book",
             "The current SICR test uses a relative PD threshold that puts "
             "most of the shipping book into Stage 2 permanently. Committee "
             "needs to decide between a segment-specific threshold and an "
             "absolute floor.",
             "HIGH", "OPEN", "amina.hassan", 25,
             "", ""),
            ("DECISION", "Model scope: corporate only, or corporate and SME",
             "Extending to SME adds roughly six weeks. Decided at the "
             "September steering committee: corporate only for this cycle.",
             "MEDIUM", "CLOSED", "amina.hassan", -30, "",
             "Corporate only. SME to be scheduled separately in the next "
             "model plan."),
            ("ISSUE", "Valuation policy not issued",
             "Collateral haircut work cannot start until Credit Policy "
             "issues the updated valuation policy.",
             "HIGH", "OPEN", "samir.khoury", 10,
             "Raised at steering; Credit Policy to confirm a date.", ""),
            ("ASSUMPTION", "Macro scenarios remain the group set",
             "The redeveloped model uses the group's published macro "
             "scenarios unchanged. If Economics reweights them mid-project "
             "the impact analysis has to be rerun.",
             "MEDIUM", "OPEN", "amina.hassan", 60, "", ""),
        ],
        #: A fortnight of history, so "what changed since Friday?" has an
        #: answer. Each is (task code or None, author, days ago, narrative).
        "updates": [
            (None, "priya.raman", 13,
             "Steering committee held. Scope confirmed as corporate only for "
             "this cycle; SME deferred."),
            ("T-301", "tom.whitfield", 11,
             "Workout extraction at 60%. The 2018-19 recovery files are "
             "missing collateral realisation dates."),
            ("T-202", "daniel.okafor", 9,
             "Four candidate specifications fitted. Gini on the holdout is "
             "0.61 to 0.68; stability is the differentiator."),
            ("T-302", "samir.khoury", 8,
             "Still no valuation policy from Credit Policy. Chased again."),
            ("T-202a", "daniel.okafor", 6,
             "Shipping segmentation needs the vessel-age field, which is not "
             "in the extract. Raised with Tom."),
            ("T-301", "tom.whitfield", 5,
             "Extraction at 80%. Two recovery files left to load."),
            (None, "priya.raman", 4,
             "Weekly report: PD on track for M-2, LGD at risk on the "
             "valuation policy, no change to the end date."),
            ("T-402", "priya.raman", 2,
             "Drafted the quantitative SICR test. Needs the shipping "
             "decision before it can be finalised."),
            ("T-202", "daniel.okafor", 1,
             "Down to two candidates. Selection meeting booked."),
        ],
    }


def build(force: bool = False, check: bool = False) -> Report:
    report = Report()
    try:
        from backend.config import settings
    except Exception as exc:  # pragma: no cover - misconfigured checkout
        report.error = f"configuration could not be read: {exc}"
        return report
    if not settings.has_database:
        report.error = "No DATABASE_URL. The Project Planner needs PostgreSQL."
        return report

    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.models.planner import PlannerProject
    from backend.planner import query as pq
    from backend.planner import service as svc

    with get_session() as session:
        existing = session.execute(
            select(PlannerProject).where(
                PlannerProject.code == PROJECT_CODE)).scalar_one_or_none()
        if existing is not None and not force:
            report.project_id = int(existing.id)
            report.notes.append(
                f"{PROJECT_CODE} already exists (project {existing.id}). "
                "Use --force to rebuild it.")
            return report
        if check:
            report.notes.append(
                f"{PROJECT_CODE} is absent and would be built.")
            return report
        if existing is not None:
            session.delete(existing)
            session.flush()
            report.notes.append(f"replaced the previous {PROJECT_CODE}.")

        people = _people(session)
        shape = plan(date.today())
        who = Seeder(people["priya.raman"])

        project = svc.create_project(
            session, who, manager_id=people["priya.raman"],
            sponsor_id=people["amina.hassan"], **shape["project"])
        session.flush()
        pid = int(project.id)
        report.project_id = pid

        for username, role, access in shape["participants"]:
            if people[username] == who.user_id:
                continue  # the creator is already an owner
            svc.add_participant(session, who, pid, user_id=people[username],
                                project_role=role, access=access)

        ws_ids: dict[str, int] = {}
        for code, name, lead, order, start, end in shape["workstreams"]:
            row = svc.create_workstream(
                session, who, pid, code=code, name=name,
                lead_id=people[lead], sequence=order,
                start_date=(date.today() + timedelta(days=start)).isoformat(),
                target_end_date=(date.today()
                                 + timedelta(days=end)).isoformat())
            session.flush()
            ws_ids[code] = int(row.id)

        task_ids: dict[str, int] = {}
        for (code, title, ws, parent, owner, status, percent, start, due,
             weight, critical, blocked, reason, step) in shape["tasks"]:
            row = svc.create_task(
                session, who, pid, code=code, title=title,
                workstream_id=ws_ids[ws],
                parent_id=task_ids.get(parent) if parent else None,
                owner_id=people[owner], status=status,
                percent_complete=percent,
                start_date=(date.today() + timedelta(days=start)).isoformat(),
                due_date=(date.today() + timedelta(days=due)).isoformat(),
                weight=weight, critical=critical, blocked=blocked,
                blocker_reason=reason, next_step=step)
            session.flush()
            task_ids[code] = int(row.id)

        ms_ids: dict[str, int] = {}
        for code, name, ws, owner, when, status, critical in \
                shape["milestones"]:
            row = svc.create_milestone(
                session, who, pid, code=code, name=name,
                workstream_id=ws_ids[ws], owner_id=people[owner],
                target_date=(date.today() + timedelta(days=when)).isoformat(),
                status=status, critical=critical)
            session.flush()
            ms_ids[code] = int(row.id)

        def entity(kind: str, code: str) -> int:
            return task_ids[code] if kind == "TASK" else ms_ids[code]

        for from_kind, from_code, to_kind, to_code, link, lag in \
                shape["dependencies"]:
            svc.create_dependency(
                session, who, pid, predecessor_type=from_kind,
                predecessor_id=entity(from_kind, from_code),
                successor_type=to_kind,
                successor_id=entity(to_kind, to_code),
                dependency_type=link, lag_days=lag)

        for (kind, title, description, severity, status, owner, when,
             mitigation, resolution) in shape["raid"]:
            svc.create_raid(
                session, who, pid, raid_type=kind, title=title,
                description=description, severity=severity, status=status,
                owner_id=people[owner],
                target_date=(date.today() + timedelta(days=when)).isoformat(),
                mitigation=mitigation, resolution=resolution)

        for task_code, author, _ago, narrative in shape["updates"]:
            speaker = Seeder(people[author])
            svc.post_update(
                session, speaker, pid, narrative=narrative,
                entity_type="TASK" if task_code else "PROJECT",
                entity_id=task_ids[task_code] if task_code else None)

        # The history rows above were all written "now" because the service
        # stamps them itself, which is right — it must not be possible to
        # backdate the record through an ordinary write. The seed is the one
        # legitimate exception, so it adjusts them afterwards, in one place,
        # visibly.
        _backdate(session, pid, shape["updates"])

        session.flush()
        pq.refresh_calculations(session, project)
        session.commit()

        counts = _counts(session, pid)
        report.built = True
        report.counts = counts
    return report


def _backdate(session: Any, project_id: int,
              updates: list[tuple]) -> None:
    """Spread the seeded history back over the fortnight it describes.

    Done by direct UPDATE and only here. Every other path in the product
    stamps `created_at` from the server clock, and it stays that way: a
    history somebody can backdate is not evidence of anything.
    """
    from datetime import UTC, datetime

    from sqlalchemy import select

    from backend.models.planner import PlannerUpdate

    rows = list(session.execute(
        select(PlannerUpdate)
        .where(PlannerUpdate.project_id == project_id,
               PlannerUpdate.action == "comment")
        .order_by(PlannerUpdate.id)).scalars())
    now = datetime.now(UTC)
    for row, (_code, _author, ago, _text) in zip(rows, updates, strict=False):
        row.created_at = now - timedelta(days=int(ago))


def _counts(session: Any, project_id: int) -> dict[str, int]:
    from sqlalchemy import func, select

    from backend.models.planner import (
        PlannerDependency,
        PlannerMilestone,
        PlannerParticipant,
        PlannerRaid,
        PlannerTask,
        PlannerUpdate,
        PlannerWorkstream,
    )

    def count(model: Any) -> int:
        return int(session.execute(
            select(func.count()).select_from(model)
            .where(model.project_id == project_id)).scalar() or 0)

    return {
        "participants": count(PlannerParticipant),
        "workstreams": count(PlannerWorkstream),
        "tasks": count(PlannerTask),
        "milestones": count(PlannerMilestone),
        "dependencies": count(PlannerDependency),
        "raid": count(PlannerRaid),
        "updates": count(PlannerUpdate),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build(force=args.force, check=args.check)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"! {report.error}")
        for note in report.notes:
            print(f"  {note}")
        if report.built:
            print(f"  built {PROJECT_CODE} as project {report.project_id}")
            for name, number in report.counts.items():
                print(f"    {name:14s} {number}")

    if report.error:
        return EXIT_CANNOT_RUN
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
