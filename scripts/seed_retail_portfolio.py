#!/usr/bin/env python
"""Four Retail Credit Risk programmes, as a bank actually runs them.

    python scripts/seed_retail_portfolio.py                    build what is missing
    python scripts/seed_retail_portfolio.py --check           report only
    python scripts/seed_retail_portfolio.py --refresh-dates   roll dates to today
    python scripts/seed_retail_portfolio.py --refresh-dates --dry-run
    python scripts/seed_retail_portfolio.py --reset           rebuild from scratch
    python scripts/seed_retail_portfolio.py --json            machine-readable

This is the `planner-demo` command surface: everything that creates, inspects,
re-anchors or rebuilds the demonstration programmes is here, because a second
entry point is a second set of guards to keep in step with these.

Dates go stale, and rebuilding is the wrong repair
--------------------------------------------------
Every date below is an offset from the day the seed ran, which is true that day
and decays afterwards: a sign-off due in three days is due in two tomorrow, two
is not a reminder threshold, and the demonstration stops being able to fire on
its own. `--refresh-dates` rolls every scheduling field forward by the days
since it was anchored and leaves everything else — progress, status, owners,
narrative, RAID, history — exactly as it is. `--dry-run` prints what would move
and changes nothing. A date a person moved themselves is held back and
reported, because that is a commitment somebody made; `--force-demo-dates`
overwrites it, and says so. See `backend/planner/demo.py`.

Why four, and why this much detail
----------------------------------
A planner shown with four projects of five generic tasks each demonstrates a
table. What a Head of Retail Credit Risk needs to see before believing one is
the shape of their own week: a monthly ECL production run with a data freeze
somebody missed, a scorecard redevelopment waiting on a validation opinion, a
collections pilot that has not started because Legal has not cleared the
wording, and a remediation programme that is red because a dependency slipped
and took a regulatory commitment with it.

So each programme carries real workstreams, real task names, subtasks,
dependencies that mean something, milestones somebody is judged on, RAID items
with owners, and — deliberately — work that is complete, in progress, due
today, due soon, overdue, blocked with a reason, stale, and awaiting review.
The health of each falls out of the rules rather than being set: GREEN, AMBER
and RED here are calculated, and if the rules change the colours change with
them.

Relative dates, always
----------------------
Every date is an offset from the day it is seeded. A demonstration in March
and the same demonstration in November both show something overdue by the
right amount. Nothing is pinned to a month.

What it will not do
-------------------
Every row goes through `backend.planner.service` with a named author, so
everything it creates is subject to the same validation, permissions, history
and audit as a row a person would have typed. A seed that inserted directly
could create states the product cannot reach, which is how a demonstration
ends up showing something that cannot happen.

`--reset` is guarded: it refuses outside a development or demonstration
deployment, and it removes only the four programmes named here.
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

from backend.planner import demo  # noqa: E402 - after the path is set up

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_CANNOT_RUN = 2

IFRS9 = "RET-IFRS9"
SCORECARD = "RET-SCORECARD"
COLLECTIONS = "RET-COLLECTIONS"
REMEDIATION = "RET-DATA-REM"
CODES = (IFRS9, SCORECARD, COLLECTIONS, REMEDIATION)

#: The cast. Real roles from a retail credit risk function, and deliberately
#: NOT all owners: the access column is what makes the permission story
#: demonstrable, and a demonstration where everybody can change everything
#: proves nothing about the permission model.
CAST: tuple[tuple[str, str, str, str, str], ...] = (
    ("ananya.shah", "Ananya", "Shah", "ANALYST",
     "Head of Retail Credit Risk"),
    ("priya.raman", "Priya", "Raman", "ANALYST",
     "Retail Risk Transformation Lead"),
    ("rohan.mehta", "Rohan", "Mehta", "ANALYST",
     "Retail Credit Modelling Lead"),
    ("neha.kapoor", "Neha", "Kapoor", "ANALYST",
     "IFRS 9 / Provisioning Lead"),
    ("sameer.iqbal", "Sameer", "Iqbal", "ANALYST", "Retail Risk Data Lead"),
    ("fatima.khan", "Fatima", "Khan", "ANALYST", "Finance Controller"),
    ("daniel.lee", "Daniel", "Lee", "VIEWER",
     "Independent Model Validation Lead"),
    ("maya.singh", "Maya", "Singh", "ANALYST", "Collections Strategy Lead"),
    ("omar.rahman", "Omar", "Rahman", "ANALYST",
     "Technology / Decision Engine Lead"),
    ("kavita.rao", "Kavita", "Rao", "VIEWER", "Retail Credit Policy Lead"),
)


class Seeder:
    """Just enough of a principal for the service layer."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, _allowed: Any) -> bool:
        return True


@dataclass
class Report:
    built: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    health: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"built": self.built, "skipped": self.skipped,
                "removed": self.removed, "counts": self.counts,
                "health": self.health, "notes": self.notes,
                "error": self.error}


def _may_reset() -> tuple[bool, str]:
    """Whether destructive work is allowed here.

    Two ways to be sure this is not a production deployment: the environment
    says so, or Demo Mode is on. Both are explicit; neither can be acquired by
    forgetting to set something.
    """
    from backend.config import settings
    from backend.demo import mode

    if mode.enabled():
        return True, "Synthetic Data Mode is on."
    if str(settings.env or "").lower() in {"dev", "development", "test",
                                           "demo", "local"}:
        return True, f"ENV is {settings.env}."
    return False, (
        f"ENV is {settings.env!r} and Synthetic Data Mode is off. --reset "
        "removes projects, so it refuses to run anywhere that might be real.")


def _people(session: Any) -> dict[str, int]:
    from sqlalchemy import select

    from backend.db.models import User

    found: dict[str, int] = {}
    for username, first, last, role, title in CAST:
        existing = session.execute(
            select(User).where(User.username == username)).scalar_one_or_none()
        if existing is None:
            from backend.auth.security import hash_password
            from backend.services.demo_users import DEMO_PASSWORD

            existing = User(
                username=username, password_hash=hash_password(DEMO_PASSWORD),
                role=role, first_name=first, last_name=last,
                email=f"{username}@example.invalid", job_title=title,
                department="Retail Credit Risk", team="Retail Risk",
                is_active=True)
            session.add(existing)
            session.flush()
        elif not (existing.job_title or "").strip():
            # An account another seed created without a title. Filling it in
            # is safe; a password is never touched, for the reason the demo
            # user service gives: re-seeding one would be a published back
            # door on any deployment that happens to have this username.
            existing.job_title = title
        found[username] = int(existing.id)
    return found


def _d(today: date, offset: int) -> str:
    return (today + timedelta(days=offset)).isoformat()


# =========================================================== the programmes
#
# Each programme is one structure rather than a hundred service calls, so the
# shape is reviewable: somebody checking that the IFRS 9 run contains a task
# due in three days at 30% — the one the agentic demonstration turns on — can
# see it without reading imperative code.
#
# Task tuples are:
#   code, title, workstream, parent, owner, status, percent,
#   start offset, due offset, weight, critical, blocked, blocker, next step


def ifrs9(today: date) -> dict[str, Any]:
    """The monthly ECL production run. AMBER: overdue data work and a
    high-severity overlay question, with the critical chain still intact."""
    month = today.strftime("%B %Y")
    return {
        "code": IFRS9,
        "name": f"Retail IFRS 9 — {month} ECL Production Run",
        "status": "ACTIVE", "priority": "CRITICAL",
        "objective": (
            "Complete the Retail IFRS 9 impairment production cycle: data "
            "validation, staging, model calculations, macroeconomic "
            "scenarios, management overlays, Finance reconciliation and "
            "final ECL sign-off."),
        "business_context": (
            "The monthly retail impairment cycle feeds the group provision "
            "and the regulatory return. It has a hard posting date and a "
            "Finance reconciliation that cannot start until the ECL run "
            "completes."),
        "start": -18, "end": 12, "cadence": "WEEKLY", "stale": 4,
        "participants": [
            ("ananya.shah", "SPONSOR", "OWNER"),
            ("neha.kapoor", "PROJECT_MANAGER", "OWNER"),
            ("sameer.iqbal", "WORKSTREAM_LEAD", "EDITOR"),
            ("rohan.mehta", "WORKSTREAM_LEAD", "EDITOR"),
            ("fatima.khan", "REVIEWER", "CONTRIBUTOR"),
            ("priya.raman", "CONTRIBUTOR", "CONTRIBUTOR"),
            ("daniel.lee", "REVIEWER", "VIEWER"),
            ("kavita.rao", "VIEWER", "VIEWER"),
        ],
        "manager": "neha.kapoor",
        "sponsor": "ananya.shah",
        "workstreams": [
            ("WS-DATA", "Data and controls", "sameer.iqbal", 1, -18, -10),
            ("WS-STAGE", "SICR and staging", "rohan.mehta", 2, -11, -4),
            ("WS-PARAM", "PD, LGD and EAD", "rohan.mehta", 3, -11, -3),
            ("WS-MACRO", "Macroeconomic scenarios", "rohan.mehta", 4, -8, -2),
            ("WS-OVER", "Management overlays", "neha.kapoor", 5, -4, 4),
            ("WS-ECL", "ECL production", "neha.kapoor", 6, -3, 5),
            ("WS-GOV", "Governance and sign-off", "ananya.shah", 7, 3, 12),
        ],
        "tasks": [
            # --- data and controls
            ("T-101", "Portfolio snapshot extraction", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -18, -15, 3, True, False, "", ""),
            ("T-101a", "Personal loans snapshot", "WS-DATA", "T-101",
             "sameer.iqbal", "COMPLETED", 100, -18, -16, 1, False, False, "", ""),
            ("T-101b", "Cards snapshot", "WS-DATA", "T-101",
             "sameer.iqbal", "COMPLETED", 100, -18, -16, 1, False, False, "", ""),
            ("T-101c", "Mortgages snapshot", "WS-DATA", "T-101",
             "sameer.iqbal", "COMPLETED", 100, -18, -15, 1, False, False, "", ""),
            ("T-101d", "Consumer finance snapshot", "WS-DATA", "T-101",
             "sameer.iqbal", "COMPLETED", 100, -18, -15, 1, False, False, "", ""),
            ("T-102", "Source-to-target reconciliation", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -15, -12, 3, True, False, "", ""),
            ("T-102a", "Account counts", "WS-DATA", "T-102",
             "sameer.iqbal", "COMPLETED", 100, -15, -13, 1, False, False, "", ""),
            ("T-102b", "Outstanding balance and EAD", "WS-DATA", "T-102",
             "fatima.khan", "COMPLETED", 100, -15, -13, 1, False, False, "", ""),
            ("T-102c", "Days past due", "WS-DATA", "T-102",
             "sameer.iqbal", "COMPLETED", 100, -14, -12, 1, False, False, "", ""),
            ("T-103", "Data quality exceptions", "WS-DATA", None,
             "sameer.iqbal", "IN_PROGRESS", 60, -13, -2, 2, False, False,
             "", "Clear the remaining 240 missing origination dates."),
            ("T-103a", "Missing origination dates", "WS-DATA", "T-103",
             "sameer.iqbal", "IN_PROGRESS", 40, -13, -2, 1, False, False, "", ""),
            ("T-103b", "Missing behavioural scores", "WS-DATA", "T-103",
             "sameer.iqbal", "COMPLETED", 100, -13, -8, 1, False, False, "", ""),
            ("T-103c", "Delinquency inconsistencies", "WS-DATA", "T-103",
             "sameer.iqbal", "NOT_STARTED", 0, -6, -1, 1, False, False, "", ""),

            # --- staging
            ("T-201", "Current PD calculation", "WS-STAGE", None,
             "rohan.mehta", "COMPLETED", 100, -11, -9, 2, True, False, "", ""),
            ("T-202", "Origination versus current risk comparison",
             "WS-STAGE", None, "rohan.mehta", "COMPLETED", 100, -10, -8,
             2, False, False, "", ""),
            ("T-203", "Quantitative SICR assessment", "WS-STAGE", None,
             "rohan.mehta", "COMPLETED", 100, -9, -7, 2, True, False, "", ""),
            ("T-204", "Qualitative SICR triggers", "WS-STAGE", None,
             "kavita.rao", "COMPLETED", 100, -9, -6, 1, False, False, "", ""),
            ("T-205", "Stage 1 and Stage 2 validation", "WS-STAGE", None,
             "daniel.lee", "IN_REVIEW", 90, -7, -1, 2, False, False,
             "", "Validation opinion expected today."),
            ("T-206", "Stage 3 and default population", "WS-STAGE", None,
             "rohan.mehta", "COMPLETED", 100, -7, -5, 2, False, False, "", ""),
            ("T-207", "Cure review", "WS-STAGE", None,
             "rohan.mehta", "COMPLETED", 100, -6, -4, 1, False, False, "", ""),

            # --- parameters
            ("T-301", "Behavioural PD inputs", "WS-PARAM", None,
             "rohan.mehta", "COMPLETED", 100, -11, -8, 2, False, False, "", ""),
            ("T-302", "Lifetime PD term structure", "WS-PARAM", None,
             "rohan.mehta", "COMPLETED", 100, -10, -6, 3, True, False, "", ""),
            ("T-303", "LGD and cure assumptions", "WS-PARAM", None,
             "rohan.mehta", "COMPLETED", 100, -9, -5, 2, False, False, "", ""),
            ("T-304", "EAD and CCF", "WS-PARAM", None,
             "rohan.mehta", "COMPLETED", 100, -9, -5, 2, False, False, "", ""),
            ("T-305", "Prior-month movement review", "WS-PARAM", None,
             "neha.kapoor", "IN_PROGRESS", 45, -6, -1, 2, False, False,
             "", "Explain the 4% Stage 2 increase in cards."),

            # --- macro
            ("T-401", "Base scenario", "WS-MACRO", None,
             "rohan.mehta", "COMPLETED", 100, -8, -6, 2, True, False, "", ""),
            ("T-402", "Upside scenario", "WS-MACRO", None,
             "rohan.mehta", "COMPLETED", 100, -8, -6, 1, False, False, "", ""),
            ("T-403", "Downside scenario", "WS-MACRO", None,
             "rohan.mehta", "COMPLETED", 100, -8, -6, 1, False, False, "", ""),
            ("T-404", "Scenario weights approval", "WS-MACRO", None,
             "ananya.shah", "COMPLETED", 100, -6, -4, 2, False, False, "", ""),
            ("T-405", "Scenario-conditioned ECL", "WS-MACRO", None,
             "rohan.mehta", "COMPLETED", 100, -5, -3, 2, True, False, "", ""),

            # --- overlays: the demonstration turns here
            ("T-501", "Emerging risk review", "WS-OVER", None,
             "neha.kapoor", "COMPLETED", 100, -4, -2, 2, False, False, "", ""),
            ("T-502", "Candidate overlay quantification", "WS-OVER", None,
             "rohan.mehta", "COMPLETED", 100, -3, -1, 2, False, False, "", ""),
            ("T-503", "Management Overlay Sign-off", "WS-OVER", None,
             "fatima.khan", "IN_PROGRESS", 30, -2, 3, 3, True, False, "",
             "Finance review of the overlay calculation."),
            ("T-504", "Overlay rationale documentation", "WS-OVER", None,
             "neha.kapoor", "NOT_STARTED", 0, 2, 5, 1, False, False, "", ""),

            # --- ECL production
            ("T-601", "Stage 1 twelve-month ECL", "WS-ECL", None,
             "rohan.mehta", "COMPLETED", 100, -3, -1, 2, True, False, "", ""),
            ("T-602", "Stage 2 lifetime ECL", "WS-ECL", None,
             "rohan.mehta", "COMPLETED", 100, -3, -1, 2, True, False, "", ""),
            ("T-603", "Stage 3 ECL", "WS-ECL", None,
             "rohan.mehta", "COMPLETED", 100, -3, -1, 2, False, False, "", ""),
            ("T-604", "ECL consolidation", "WS-ECL", None,
             "neha.kapoor", "IN_PROGRESS", 75, -1, 1, 3, True, False, "",
             "Consolidate once the overlay is signed off."),
            ("T-605", "Prior-period reconciliation and movement",
             "WS-ECL", None, "neha.kapoor", "NOT_STARTED", 0, 1, 4,
             2, False, False, "", ""),
            ("T-606", "Finance reconciliation", "WS-ECL", None,
             "fatima.khan", "NOT_STARTED", 0, 3, 6, 3, True, True,
             "Waiting on the consolidated ECL run, which is waiting on the "
             "overlay sign-off.", ""),

            # --- governance
            ("T-701", "Retail Risk review", "WS-GOV", None,
             "ananya.shah", "NOT_STARTED", 0, 5, 7, 2, False, False, "", ""),
            ("T-702", "Impairment pack", "WS-GOV", None,
             "neha.kapoor", "NOT_STARTED", 0, 6, 8, 2, False, False, "", ""),
            ("T-703", "CRO review and sign-off", "WS-GOV", None,
             "ananya.shah", "NOT_STARTED", 0, 8, 10, 3, True, False, "", ""),
            ("T-704", "Month-end posting handoff", "WS-GOV", None,
             "fatima.khan", "NOT_STARTED", 0, 10, 12, 2, True, False, "", ""),
        ],
        "milestones": [
            ("M-1", "Data Freeze", "sameer.iqbal", -10, "ACHIEVED", True),
            ("M-2", "Staging Complete", "rohan.mehta", -4, "ACHIEVED", True),
            ("M-3", "ECL Run Complete", "neha.kapoor", 1, "PENDING", True),
            ("M-4", "Finance Reconciliation", "fatima.khan", 6, "PENDING", True),
            ("M-5", "CRO Sign-off", "ananya.shah", 10, "PENDING", True),
            ("M-6", "Month-End Posting", "fatima.khan", 12, "PENDING", True),
        ],
        "dependencies": [
            ("TASK", "T-102", "TASK", "T-201", "FS", 0),
            ("TASK", "T-201", "TASK", "T-203", "FS", 0),
            ("TASK", "T-203", "TASK", "T-205", "FS", 0),
            ("TASK", "T-302", "TASK", "T-405", "FS", 0),
            ("TASK", "T-405", "TASK", "T-601", "FS", 0),
            ("TASK", "T-405", "TASK", "T-602", "FS", 0),
            ("TASK", "T-503", "TASK", "T-604", "FS", 0),
            ("TASK", "T-604", "TASK", "T-606", "FS", 0),
            ("TASK", "T-606", "TASK", "T-703", "FS", 1),
            ("TASK", "T-703", "TASK", "T-704", "FS", 0),
            ("TASK", "T-604", "MILESTONE", "M-3", "FS", 0),
            ("TASK", "T-606", "MILESTONE", "M-4", "FS", 0),
            ("TASK", "T-703", "MILESTONE", "M-5", "FS", 0),
            ("TASK", "T-704", "MILESTONE", "M-6", "FS", 0),
        ],
        "raid": [
            ("RISK", "Overlay sign-off may not clear before the posting date",
             "HIGH", "OPEN", "fatima.khan",
             "The Finance review of the management overlay is the last thing "
             "between the ECL run and the reconciliation, and it is the only "
             "item on the critical chain with no float behind it.",
             "Daily check-in with Finance until it clears.", 3),
            ("ISSUE", "240 accounts still carry no origination date",
             "MEDIUM", "OPEN", "sameer.iqbal",
             "The exception clearing is behind. Affected accounts default to "
             "the portfolio-average origination PD, which weakens the SICR "
             "comparison for that population.",
             "Source them from the archive extract.", -1),
            ("DECISION",
             "Whether to hold the cards overlay at last month's level",
             "MEDIUM", "OPEN", "neha.kapoor",
             "Cards Stage 2 is up four points on the month. Holding the "
             "overlay flat assumes the movement is seasonal.",
             "", 2),
            ("ASSUMPTION",
             "Scenario weights unchanged from the approved set",
             "LOW", "ACCEPTED", "rohan.mehta",
             "No macro committee has met since the last approval.", "", -4),
        ],
    }


def scorecard(today: date) -> dict[str, Any]:
    """The application scorecard redevelopment. AMBER for a real reason: the
    validation opinion is late and the committee date behind it has not
    moved."""
    return {
        "code": SCORECARD,
        "name": "Retail Application Scorecard Redevelopment",
        "status": "ACTIVE", "priority": "HIGH",
        "objective": (
            "Redevelop the retail application scorecard on a current "
            "observation window, validate it independently, and implement it "
            "in the decision engine with a monitored parallel run."),
        "business_context": (
            "The incumbent application scorecard was built on a 2019 "
            "observation window. Its Gini has fallen two years running and "
            "Model Risk has raised the population stability index on the "
            "digital channel as a high-severity finding."),
        "start": -150, "end": 120, "cadence": "WEEKLY", "stale": 10,
        "manager": "priya.raman",
        "sponsor": "ananya.shah",
        "participants": [
            ("ananya.shah", "SPONSOR", "OWNER"),
            ("priya.raman", "PROJECT_MANAGER", "OWNER"),
            ("rohan.mehta", "WORKSTREAM_LEAD", "EDITOR"),
            ("sameer.iqbal", "WORKSTREAM_LEAD", "EDITOR"),
            ("daniel.lee", "REVIEWER", "VIEWER"),
            ("kavita.rao", "REVIEWER", "CONTRIBUTOR"),
            ("omar.rahman", "CONTRIBUTOR", "CONTRIBUTOR"),
        ],
        "workstreams": [
            ("WS-DEF", "Project definition", "priya.raman", 1, -150, -120),
            ("WS-DATA", "Data", "sameer.iqbal", 2, -125, -85),
            ("WS-EDA", "Exploratory analysis", "rohan.mehta", 3, -90, -65),
            ("WS-DEV", "Development", "rohan.mehta", 4, -70, -25),
            ("WS-PERF", "Performance testing", "rohan.mehta", 5, -30, -5),
            ("WS-POL", "Policy integration", "kavita.rao", 6, -20, 20),
            ("WS-VAL", "Independent validation", "daniel.lee", 7, -10, 25),
            ("WS-GOV", "Governance", "priya.raman", 8, 25, 55),
            ("WS-TECH", "Technology", "omar.rahman", 9, 40, 120),
        ],
        "tasks": [
            ("S-101", "Portfolio scope and exclusions", "WS-DEF", None,
             "priya.raman", "COMPLETED", 100, -150, -140, 2, False, False, "", ""),
            ("S-102", "Observation and performance windows", "WS-DEF", None,
             "rohan.mehta", "COMPLETED", 100, -148, -138, 2, True, False, "", ""),
            ("S-103", "Bad definition", "WS-DEF", None,
             "rohan.mehta", "COMPLETED", 100, -145, -132, 3, True, False, "", ""),
            ("S-104", "Governance approval of the definition", "WS-DEF", None,
             "ananya.shah", "COMPLETED", 100, -132, -122, 2, False, False, "", ""),

            ("S-201", "Application data assembly", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -125, -110, 2, False, False, "", ""),
            ("S-202", "Bureau data assembly", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -125, -105, 2, False, False, "", ""),
            ("S-203", "Performance outcome join", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -108, -95, 2, True, False, "", ""),
            ("S-204", "Missingness and exclusion review", "WS-DATA", None,
             "sameer.iqbal", "COMPLETED", 100, -100, -90, 1, False, False, "", ""),
            ("S-205", "Modelling dataset sign-off", "WS-DATA", None,
             "daniel.lee", "COMPLETED", 100, -92, -85, 2, False, False, "", ""),

            ("S-301", "Univariate analysis", "WS-EDA", None,
             "rohan.mehta", "COMPLETED", 100, -90, -80, 2, False, False, "", ""),
            ("S-302", "Discriminatory power by variable", "WS-EDA", None,
             "rohan.mehta", "COMPLETED", 100, -85, -75, 2, False, False, "", ""),
            ("S-303", "Stability and correlation screening", "WS-EDA", None,
             "rohan.mehta", "COMPLETED", 100, -80, -68, 2, False, False, "", ""),
            ("S-304", "Candidate variable list", "WS-EDA", None,
             "rohan.mehta", "COMPLETED", 100, -72, -65, 2, True, False, "", ""),

            ("S-401", "Binning and monotonicity", "WS-DEV", None,
             "rohan.mehta", "COMPLETED", 100, -70, -55, 2, False, False, "", ""),
            ("S-402", "Weight of evidence transformation", "WS-DEV", None,
             "rohan.mehta", "COMPLETED", 100, -60, -48, 2, False, False, "", ""),
            ("S-403", "Logistic model fitting", "WS-DEV", None,
             "rohan.mehta", "COMPLETED", 100, -55, -40, 3, True, False, "", ""),
            ("S-404", "Variable selection and coefficient review", "WS-DEV",
             None, "rohan.mehta", "COMPLETED", 100, -45, -33, 2, False, False,
             "", ""),
            ("S-405", "Scaling and scorecard construction", "WS-DEV", None,
             "rohan.mehta", "COMPLETED", 100, -35, -25, 3, True, False, "", ""),

            ("S-501", "Gini and AUROC", "WS-PERF", None,
             "rohan.mehta", "COMPLETED", 100, -30, -22, 2, False, False, "", ""),
            ("S-502", "KS statistic", "WS-PERF", None,
             "rohan.mehta", "COMPLETED", 100, -30, -22, 1, False, False, "", ""),
            ("S-503", "Calibration: observed versus predicted", "WS-PERF",
             None, "rohan.mehta", "COMPLETED", 100, -26, -18, 2, True, False,
             "", ""),
            ("S-504", "Population stability index", "WS-PERF", None,
             "rohan.mehta", "COMPLETED", 100, -24, -16, 2, False, False, "", ""),
            ("S-505", "Bad rate by score band", "WS-PERF", None,
             "rohan.mehta", "COMPLETED", 100, -22, -14, 1, False, False, "", ""),
            ("S-506", "Out-of-time validation", "WS-PERF", None,
             "rohan.mehta", "COMPLETED", 100, -18, -8, 3, True, False, "", ""),
            ("S-507", "Segment performance analysis", "WS-PERF", None,
             "rohan.mehta", "IN_PROGRESS", 70, -14, -4, 2, False, False, "",
             "Finish the self-employed segment."),

            ("S-601", "Score cut-off options", "WS-POL", None,
             "kavita.rao", "IN_PROGRESS", 55, -20, 4, 3, True, False, "",
             "Acceptance-rate and bad-rate trade-off for three cut-offs."),
            ("S-602", "Override policy", "WS-POL", None,
             "kavita.rao", "NOT_STARTED", 0, 2, 12, 2, False, False, "", ""),
            ("S-603", "Affordability and bureau rule interaction", "WS-POL",
             None, "kavita.rao", "NOT_STARTED", 0, 6, 20, 2, False, False,
             "", ""),

            ("S-701", "Conceptual soundness review", "WS-VAL", None,
             "daniel.lee", "COMPLETED", 100, -10, -4, 2, False, False, "", ""),
            ("S-702", "Independent replication", "WS-VAL", None,
             "daniel.lee", "IN_PROGRESS", 40, -6, 2, 3, True, False, "",
             "Replication of the fitted coefficients."),
            ("S-703", "Sensitivity and limitations", "WS-VAL", None,
             "daniel.lee", "NOT_STARTED", 0, -1, 8, 2, False, False, "", ""),
            ("S-704", "Validation report", "WS-VAL", None,
             "daniel.lee", "NOT_STARTED", 0, 8, 25, 3, True, False, "", ""),

            ("S-801", "Development Committee", "WS-GOV", None,
             "priya.raman", "NOT_STARTED", 0, 25, 30, 2, False, False, "", ""),
            ("S-802", "Validation Committee", "WS-GOV", None,
             "daniel.lee", "NOT_STARTED", 0, 32, 38, 2, True, False, "", ""),
            ("S-803", "Retail Credit Committee approval", "WS-GOV", None,
             "ananya.shah", "NOT_STARTED", 0, 45, 55, 3, True, False, "", ""),

            ("S-901", "Implementation specification", "WS-TECH", None,
             "omar.rahman", "NOT_STARTED", 0, 40, 55, 2, False, False, "", ""),
            ("S-902", "Decision engine mapping", "WS-TECH", None,
             "omar.rahman", "NOT_STARTED", 0, 55, 70, 2, False, False, "", ""),
            ("S-903", "User acceptance testing", "WS-TECH", None,
             "omar.rahman", "NOT_STARTED", 0, 70, 88, 2, True, False, "", ""),
            ("S-904", "Parallel run", "WS-TECH", None,
             "omar.rahman", "NOT_STARTED", 0, 88, 108, 3, True, False, "", ""),
            ("S-905", "Production go-live", "WS-TECH", None,
             "omar.rahman", "NOT_STARTED", 0, 110, 118, 3, True, False, "", ""),
        ],
        "milestones": [
            ("M-1", "Dataset Ready", "sameer.iqbal", -85, "ACHIEVED", True),
            ("M-2", "Candidate Model Selected", "rohan.mehta", -40,
             "ACHIEVED", True),
            ("M-3", "Development Complete", "rohan.mehta", -8, "ACHIEVED", True),
            ("M-4", "Validation Complete", "daniel.lee", 25, "PENDING", True),
            ("M-5", "Credit Committee Approval", "ananya.shah", 55,
             "PENDING", True),
            ("M-6", "UAT Complete", "omar.rahman", 88, "PENDING", False),
            ("M-7", "Production Go-Live", "omar.rahman", 118, "PENDING", True),
        ],
        "dependencies": [
            ("TASK", "S-103", "TASK", "S-203", "FS", 0),
            ("TASK", "S-203", "TASK", "S-304", "FS", 0),
            ("TASK", "S-304", "TASK", "S-403", "FS", 0),
            ("TASK", "S-403", "TASK", "S-405", "FS", 0),
            ("TASK", "S-405", "TASK", "S-506", "FS", 0),
            ("TASK", "S-506", "TASK", "S-702", "FS", 0),
            ("TASK", "S-702", "TASK", "S-704", "FS", 2),
            ("TASK", "S-704", "TASK", "S-802", "FS", 3),
            ("TASK", "S-802", "TASK", "S-803", "FS", 5),
            ("TASK", "S-803", "TASK", "S-903", "FS", 10),
            ("TASK", "S-903", "TASK", "S-904", "FS", 0),
            ("TASK", "S-904", "TASK", "S-905", "FS", 2),
            ("TASK", "S-601", "TASK", "S-803", "FS", 0),
            ("TASK", "S-704", "MILESTONE", "M-4", "FS", 0),
            ("TASK", "S-803", "MILESTONE", "M-5", "FS", 0),
            ("TASK", "S-903", "MILESTONE", "M-6", "FS", 0),
            ("TASK", "S-905", "MILESTONE", "M-7", "FS", 0),
        ],
        "raid": [
            ("RISK", "Independent replication may not reproduce the "
                     "coefficients within tolerance",
             "HIGH", "OPEN", "daniel.lee",
             "Replication is the gate to the validation report, which is the "
             "gate to both committees. A failure to replicate restarts the "
             "fitting step and moves go-live by a quarter.",
             "Weekly working session between development and validation.", 2),
            ("ISSUE", "Self-employed segment performance is materially weaker",
             "MEDIUM", "IN_PROGRESS", "rohan.mehta",
             "Gini on the self-employed segment is eleven points below the "
             "portfolio. A separate cut-off may be required.",
             "Segment-specific cut-off proposal with Policy.", 10),
            ("DECISION", "Single cut-off or one per channel",
             "HIGH", "OPEN", "kavita.rao",
             "A single cut-off is simpler to govern; per-channel cut-offs "
             "recover roughly 1.4 points of acceptance at the same bad rate.",
             "", 4),
            ("ASSUMPTION",
             "The decision engine can carry the new characteristics unchanged",
             "MEDIUM", "OPEN", "omar.rahman",
             "Three of the twelve characteristics are not currently sourced "
             "at decision time.", "Confirm with the engine team.", 15),
        ],
    }


def collections(today: date) -> dict[str, Any]:
    """Collections strategy optimisation. GREEN, and it should be: this is
    what a healthy programme looks like beside three that are not."""
    return {
        "code": COLLECTIONS,
        "name": "Retail Collections Strategy Optimisation",
        "status": "ACTIVE", "priority": "MEDIUM",
        "objective": (
            "Segment the delinquent book, design treatment and contact "
            "strategies per segment, and prove them through a "
            "champion/challenger pilot before rollout."),
        "business_context": (
            "Roll rates from 1–30 into 31–60 have risen for three quarters "
            "while contact rates have fallen. The current strategy treats the "
            "whole book the same way at every bucket."),
        "start": -60, "end": 150, "cadence": "FORTNIGHTLY", "stale": 14,
        "manager": "maya.singh",
        "sponsor": "ananya.shah",
        "participants": [
            ("ananya.shah", "SPONSOR", "OWNER"),
            ("maya.singh", "PROJECT_MANAGER", "OWNER"),
            ("sameer.iqbal", "CONTRIBUTOR", "CONTRIBUTOR"),
            ("omar.rahman", "WORKSTREAM_LEAD", "EDITOR"),
            ("kavita.rao", "REVIEWER", "CONTRIBUTOR"),
            ("priya.raman", "VIEWER", "VIEWER"),
        ],
        "workstreams": [
            ("WS-PORT", "Portfolio analysis", "sameer.iqbal", 1, -60, -30),
            ("WS-SEG", "Customer segmentation", "maya.singh", 2, -40, -10),
            ("WS-TREAT", "Treatment strategy", "maya.singh", 3, -20, 25),
            ("WS-CON", "Contact strategy", "maya.singh", 4, -10, 35),
            ("WS-CC", "Champion and challenger", "maya.singh", 5, 20, 90),
            ("WS-GOV", "Conduct and governance", "kavita.rao", 6, 15, 60),
            ("WS-IMPL", "Implementation", "omar.rahman", 7, 60, 150),
        ],
        "tasks": [
            ("C-101", "Delinquency segmentation", "WS-PORT", None,
             "sameer.iqbal", "COMPLETED", 100, -60, -48, 2, False, False, "", ""),
            ("C-102", "Roll rate analysis", "WS-PORT", None,
             "sameer.iqbal", "COMPLETED", 100, -58, -44, 2, True, False, "", ""),
            ("C-103", "Cure rate analysis", "WS-PORT", None,
             "sameer.iqbal", "COMPLETED", 100, -50, -38, 2, False, False, "", ""),
            ("C-104", "Vintage and recovery curves", "WS-PORT", None,
             "sameer.iqbal", "COMPLETED", 100, -45, -32, 2, False, False, "", ""),
            ("C-105", "Contactability analysis", "WS-PORT", None,
             "maya.singh", "COMPLETED", 100, -40, -30, 1, False, False, "", ""),

            ("C-201", "Risk and balance segmentation", "WS-SEG", None,
             "maya.singh", "COMPLETED", 100, -40, -25, 2, True, False, "", ""),
            ("C-202", "Willingness and ability to pay", "WS-SEG", None,
             "maya.singh", "COMPLETED", 100, -32, -18, 2, False, False, "", ""),
            ("C-203", "Segment definitions signed off", "WS-SEG", None,
             "ananya.shah", "COMPLETED", 100, -18, -10, 2, False, False, "", ""),

            ("C-301", "Pre-delinquency treatment", "WS-TREAT", None,
             "maya.singh", "COMPLETED", 100, -20, -8, 2, False, False, "", ""),
            ("C-302", "1–30 DPD treatment", "WS-TREAT", None,
             "maya.singh", "COMPLETED", 100, -18, -6, 2, False, False, "", ""),
            ("C-303", "31–60 DPD treatment", "WS-TREAT", None,
             "maya.singh", "IN_PROGRESS", 80, -12, 4, 2, True, False, "",
             "Finalise the settlement thresholds."),
            ("C-304", "61–90 DPD treatment", "WS-TREAT", None,
             "maya.singh", "IN_PROGRESS", 45, -6, 12, 2, False, False, "", ""),
            ("C-305", "Hardship and restructuring paths", "WS-TREAT", None,
             "kavita.rao", "IN_PROGRESS", 35, 0, 25, 2, False, False, "", ""),

            ("C-401", "Digital and SMS sequencing", "WS-CON", None,
             "omar.rahman", "IN_PROGRESS", 60, -10, 8, 2, False, False, "", ""),
            ("C-402", "Outbound call prioritisation", "WS-CON", None,
             "maya.singh", "IN_PROGRESS", 50, -4, 14, 2, False, False, "", ""),
            ("C-403", "Contact frequency limits", "WS-CON", None,
             "kavita.rao", "NOT_STARTED", 0, 10, 35, 2, True, False, "", ""),

            ("C-501", "Champion and challenger design", "WS-CC", None,
             "maya.singh", "NOT_STARTED", 0, 20, 35, 3, True, False, "", ""),
            ("C-502", "Success metrics and control group", "WS-CC", None,
             "sameer.iqbal", "NOT_STARTED", 0, 30, 45, 2, False, False, "", ""),
            ("C-503", "Pilot", "WS-CC", None,
             "maya.singh", "NOT_STARTED", 0, 48, 78, 3, True, False, "", ""),
            ("C-504", "Pilot monitoring and read-out", "WS-CC", None,
             "sameer.iqbal", "NOT_STARTED", 0, 78, 90, 2, False, False, "", ""),

            ("C-601", "Conduct review", "WS-GOV", None,
             "kavita.rao", "IN_PROGRESS", 40, 15, 32, 2, True, False, "", ""),
            ("C-602", "Legal review of contact wording", "WS-GOV", None,
             "kavita.rao", "NOT_STARTED", 0, 20, 40, 2, False, False, "", ""),
            ("C-603", "Committee approval", "WS-GOV", None,
             "ananya.shah", "NOT_STARTED", 0, 45, 58, 2, True, False, "", ""),

            ("C-701", "Strategy engine configuration", "WS-IMPL", None,
             "omar.rahman", "NOT_STARTED", 0, 60, 85, 2, False, False, "", ""),
            ("C-702", "User acceptance testing", "WS-IMPL", None,
             "omar.rahman", "NOT_STARTED", 0, 90, 110, 2, True, False, "", ""),
            ("C-703", "Phased rollout", "WS-IMPL", None,
             "maya.singh", "NOT_STARTED", 0, 115, 145, 3, True, False, "", ""),
        ],
        "milestones": [
            ("M-1", "Segmentation Agreed", "maya.singh", -10, "ACHIEVED", True),
            ("M-2", "Strategy Design Complete", "maya.singh", 30,
             "PENDING", True),
            ("M-3", "Committee Approval", "ananya.shah", 58, "PENDING", True),
            ("M-4", "Pilot Complete", "maya.singh", 90, "PENDING", True),
            ("M-5", "Full Rollout", "maya.singh", 145, "PENDING", True),
        ],
        "dependencies": [
            ("TASK", "C-102", "TASK", "C-201", "FS", 0),
            ("TASK", "C-201", "TASK", "C-303", "FS", 0),
            ("TASK", "C-303", "TASK", "C-501", "FS", 2),
            ("TASK", "C-403", "TASK", "C-501", "FS", 0),
            ("TASK", "C-601", "TASK", "C-603", "FS", 5),
            ("TASK", "C-501", "TASK", "C-503", "FS", 5),
            ("TASK", "C-603", "TASK", "C-503", "FS", 0),
            ("TASK", "C-503", "TASK", "C-504", "FS", 0),
            ("TASK", "C-504", "TASK", "C-702", "FS", 10),
            ("TASK", "C-702", "TASK", "C-703", "FS", 3),
            ("TASK", "C-303", "MILESTONE", "M-2", "FS", 0),
            ("TASK", "C-603", "MILESTONE", "M-3", "FS", 0),
            ("TASK", "C-504", "MILESTONE", "M-4", "FS", 0),
            ("TASK", "C-703", "MILESTONE", "M-5", "FS", 0),
        ],
        "raid": [
            ("RISK", "Contact frequency limits may cut reachable volume",
             "MEDIUM", "IN_PROGRESS", "kavita.rao",
             "Tightening frequency caps to meet conduct expectations reduces "
             "the contactable population in the 31–60 bucket by an estimated "
             "eight per cent.",
             "Model the trade-off before the caps are set.", 30),
            ("ASSUMPTION", "The strategy engine can hold eight segments",
             "LOW", "OPEN", "omar.rahman",
             "Current configuration carries four.", "", 60),
            ("DECISION", "Whether the pilot runs on cards only or all products",
             "MEDIUM", "OPEN", "maya.singh",
             "Cards alone reads faster; all products gives a result the "
             "committee can act on once.", "", 25),
        ],
    }


def remediation(today: date) -> dict[str, Any]:
    """The data remediation programme. RED, and calculated so: a critical
    dependency slipped, a regulatory milestone is exposed behind it, and two
    critical issues are open."""
    return {
        "code": REMEDIATION,
        "name": "Retail Credit Risk Data Remediation Programme",
        "status": "ACTIVE", "priority": "CRITICAL",
        "objective": (
            "Close the data quality findings on the retail credit book: "
            "default and cure dates, origination score history, bureau "
            "snapshots, delinquency history, collateral values and the "
            "lineage and controls that keep them right."),
        "business_context": (
            "Two supervisory findings and one internal audit action depend on "
            "this programme. The default-date gaps are the reason the IFRS 9 "
            "staging comparison falls back to portfolio averages for part of "
            "the book."),
        "start": -100, "end": 60, "cadence": "WEEKLY", "stale": 7,
        "manager": "sameer.iqbal",
        "sponsor": "ananya.shah",
        "participants": [
            ("ananya.shah", "SPONSOR", "OWNER"),
            ("sameer.iqbal", "PROJECT_MANAGER", "OWNER"),
            ("priya.raman", "WORKSTREAM_LEAD", "EDITOR"),
            ("omar.rahman", "CONTRIBUTOR", "CONTRIBUTOR"),
            ("neha.kapoor", "REVIEWER", "CONTRIBUTOR"),
            ("daniel.lee", "REVIEWER", "VIEWER"),
            ("kavita.rao", "VIEWER", "VIEWER"),
        ],
        "workstreams": [
            ("WS-MAST", "Customer and account master", "sameer.iqbal", 1,
             -100, -50),
            ("WS-DEF", "Delinquency and default", "sameer.iqbal", 2, -80, 10),
            ("WS-COLL", "Collateral", "omar.rahman", 3, -70, 20),
            ("WS-BUR", "Bureau", "sameer.iqbal", 4, -60, 15),
            ("WS-HIST", "Historical performance", "priya.raman", 5, -50, 25),
            ("WS-LIN", "Lineage and controls", "priya.raman", 6, -30, 45),
            ("WS-GOV", "Governance and evidence", "sameer.iqbal", 7, 20, 60),
        ],
        "tasks": [
            ("D-101", "Duplicate customer identifiers", "WS-MAST", None,
             "sameer.iqbal", "COMPLETED", 100, -100, -78, 3, True, False, "", ""),
            ("D-102", "Account-to-customer mapping", "WS-MAST", None,
             "sameer.iqbal", "COMPLETED", 100, -90, -66, 2, False, False, "", ""),
            ("D-103", "Master data control design", "WS-MAST", None,
             "priya.raman", "COMPLETED", 100, -70, -52, 2, False, False, "", ""),

            ("D-201", "Missing default dates", "WS-DEF", None,
             "sameer.iqbal", "IN_PROGRESS", 55, -80, -12, 3, True, True,
             "The archive extract for 2019–2021 has not been released by the "
             "data warehouse team; the ticket has been open for eleven days.",
             "Escalate the extract request."),
            ("D-202", "Inconsistent cure dates", "WS-DEF", None,
             "sameer.iqbal", "IN_PROGRESS", 30, -60, -5, 2, False, False, "",
             "Cannot finish until the default dates land."),
            ("D-203", "Delinquency history gaps", "WS-DEF", None,
             "omar.rahman", "IN_PROGRESS", 65, -55, 2, 2, False, False, "", ""),
            ("D-204", "Restructure and forbearance indicators", "WS-DEF",
             None, "sameer.iqbal", "NOT_STARTED", 0, -6, 10, 2, False, False,
             "", ""),

            ("D-301", "Incomplete collateral values", "WS-COLL", None,
             "omar.rahman", "IN_PROGRESS", 70, -70, -3, 2, False, False, "", ""),
            ("D-302", "Valuation date coverage", "WS-COLL", None,
             "omar.rahman", "IN_PROGRESS", 50, -40, 8, 2, False, False, "", ""),
            ("D-303", "Collateral control testing", "WS-COLL", None,
             "daniel.lee", "NOT_STARTED", 0, 8, 20, 1, False, False, "", ""),

            ("D-401", "Missing bureau snapshots", "WS-BUR", None,
             "sameer.iqbal", "IN_PROGRESS", 40, -60, -8, 2, True, False, "",
             "Chasing the bureau for the 2020 monthly files."),
            ("D-402", "Bureau field harmonisation", "WS-BUR", None,
             "sameer.iqbal", "NOT_STARTED", 0, -4, 15, 2, False, False, "", ""),

            ("D-501", "Origination score history", "WS-HIST", None,
             "priya.raman", "IN_PROGRESS", 35, -50, -2, 3, True, False, "",
             "Reconstructing scores for the 2018 cohort."),
            ("D-502", "Performance window reconstruction", "WS-HIST", None,
             "priya.raman", "NOT_STARTED", 0, 0, 25, 2, False, False, "", ""),

            ("D-601", "Lineage documentation", "WS-LIN", None,
             "priya.raman", "IN_PROGRESS", 45, -30, 12, 2, False, False, "", ""),
            ("D-602", "Data quality control build", "WS-LIN", None,
             "omar.rahman", "IN_PROGRESS", 25, -20, 30, 2, True, False, "", ""),
            ("D-603", "Exception ownership assignment", "WS-LIN", None,
             "sameer.iqbal", "NOT_STARTED", 0, 15, 40, 2, False, False, "", ""),
            ("D-604", "Control effectiveness testing", "WS-LIN", None,
             "daniel.lee", "NOT_STARTED", 0, 30, 45, 2, True, False, "", ""),

            ("D-701", "Evidence pack for the supervisor", "WS-GOV", None,
             "sameer.iqbal", "NOT_STARTED", 0, 35, 52, 3, True, False, "", ""),
            ("D-702", "Closure submission", "WS-GOV", None,
             "ananya.shah", "NOT_STARTED", 0, 52, 58, 3, True, False, "", ""),
        ],
        "milestones": [
            ("M-1", "Master Data Clean", "sameer.iqbal", -52, "ACHIEVED", True),
            ("M-2", "Default and Cure Complete", "sameer.iqbal", -5,
             "MISSED", True),
            ("M-3", "Controls Operating", "priya.raman", 45, "PENDING", True),
            ("M-4", "Regulatory Closure Submitted", "ananya.shah", 58,
             "PENDING", True),
        ],
        "dependencies": [
            ("TASK", "D-101", "TASK", "D-201", "FS", 0),
            ("TASK", "D-201", "TASK", "D-202", "FS", 0),
            ("TASK", "D-202", "TASK", "D-502", "FS", 0),
            ("TASK", "D-201", "MILESTONE", "M-2", "FS", 0),
            ("TASK", "D-202", "MILESTONE", "M-2", "FS", 0),
            ("TASK", "D-401", "TASK", "D-501", "FS", 0),
            ("TASK", "D-501", "TASK", "D-502", "FS", 0),
            ("TASK", "D-602", "TASK", "D-604", "FS", 0),
            ("TASK", "D-604", "MILESTONE", "M-3", "FS", 0),
            ("TASK", "D-502", "TASK", "D-701", "FS", 3),
            ("TASK", "D-604", "TASK", "D-701", "FS", 0),
            ("TASK", "D-701", "TASK", "D-702", "FS", 0),
            ("TASK", "D-702", "MILESTONE", "M-4", "FS", 0),
        ],
        "raid": [
            ("ISSUE", "The 2019–2021 default archive has not been released",
             "CRITICAL", "OPEN", "sameer.iqbal",
             "Eleven days open with the warehouse team. Everything on the "
             "default and cure chain is behind it, including the missed "
             "milestone and the regulatory submission at the end of it.",
             "Escalated to the Head of Data Engineering.", -4),
            ("RISK", "The regulatory closure date is no longer achievable "
                     "on the current chain",
             "CRITICAL", "OPEN", "ananya.shah",
             "Default and Cure was missed. The submission depends on the "
             "performance reconstruction that depends on it, and there is no "
             "float left in the chain.",
             "Re-plan with the supervisor's relationship manager, or find "
             "a parallel path for the reconstruction.", 5),
            ("ISSUE", "Bureau files for 2020 are still incomplete",
             "HIGH", "IN_PROGRESS", "sameer.iqbal",
             "Four monthly snapshots missing. The bureau has acknowledged.",
             "Weekly chase; interim proxy agreed with Validation.", 8),
            ("DECISION", "Whether to reconstruct or to exclude the 2018 cohort",
             "HIGH", "OPEN", "priya.raman",
             "Reconstruction is six weeks of work; exclusion shortens the "
             "performance window and weakens the redeveloped scorecard.",
             "", 3),
            ("ASSUMPTION", "No further supervisory finding lands this cycle",
             "MEDIUM", "OPEN", "ananya.shah", "", "", 30),
        ],
    }


def programmes(today: date) -> list[dict[str, Any]]:
    return [ifrs9(today), scorecard(today), collections(today),
            remediation(today)]


# ================================================================== building


def _build_one(session: Any, who: Any, people: dict[str, int],
               spec: dict[str, Any], today: date) -> tuple[int, dict[str, int]]:
    """One programme, through the service layer, in dependency order."""
    from backend.planner import service as svc

    project = svc.create_project(
        session, who, code=spec["code"], name=spec["name"],
        status=spec["status"], priority=spec["priority"],
        objective=spec["objective"], business_context=spec["business_context"],
        sponsor_id=people[spec["sponsor"]],
        manager_id=people[spec["manager"]],
        start_date=_d(today, spec["start"]),
        target_end_date=_d(today, spec["end"]),
        reporting_cadence=spec["cadence"],
        stale_after_days=spec["stale"])
    session.flush()
    pid = int(project.id)

    # What makes this programme safe to re-anchor later, and a project a
    # person created unsafe to touch. `demo_origin` is the marker; the anchor
    # is the day every offset above was measured from, so `--refresh-dates`
    # can roll them forward by arithmetic instead of rebuilding them.
    project.demo_origin = demo.RETAIL_DEMO
    project.demo_anchor_date = today

    for username, role, access in spec["participants"]:
        if people[username] == getattr(who, "user_id", None) and (
                access != "OWNER"):
            # The creator is already an owner. A participant row that demoted
            # them would leave the project half built by somebody who can no
            # longer build it.
            continue
        svc.add_participant(session, who, pid, user_id=people[username],
                            project_role=role, access=access)
    session.flush()

    streams: dict[str, int] = {}
    for code, name, lead, order, start, end in spec["workstreams"]:
        row = svc.create_workstream(
            session, who, pid, code=code, name=name,
            lead_id=people[lead], sequence=order,
            start_date=_d(today, start), target_end_date=_d(today, end))
        session.flush()
        streams[code] = int(row.id)

    tasks: dict[str, int] = {}
    for (code, title, ws, parent, owner, status, percent, start, due,
         weight, critical, blocked, blocker, next_step) in spec["tasks"]:
        row = svc.create_task(
            session, who, pid, code=code, title=title,
            workstream_id=streams.get(ws),
            parent_id=tasks.get(parent) if parent else None,
            owner_id=people[owner], status=status, percent_complete=percent,
            start_date=_d(today, start), due_date=_d(today, due),
            weight=weight, critical=critical, blocked=blocked,
            blocker_reason=blocker, next_step=next_step)
        session.flush()
        tasks[code] = int(row.id)

    stones: dict[str, int] = {}
    for code, name, owner, target, status, critical in spec["milestones"]:
        row = svc.create_milestone(
            session, who, pid, code=code, name=name, owner_id=people[owner],
            target_date=_d(today, target), status=status, critical=critical)
        session.flush()
        stones[code] = int(row.id)

    for pred_kind, pred, succ_kind, succ, kind, lag in spec["dependencies"]:
        pred_id = (tasks if pred_kind == "TASK" else stones).get(pred)
        succ_id = (tasks if succ_kind == "TASK" else stones).get(succ)
        if pred_id is None or succ_id is None:
            raise KeyError(
                f"{spec['code']}: dependency {pred} → {succ} names something "
                "the plan does not contain.")
        svc.create_dependency(
            session, who, pid, predecessor_type=pred_kind,
            predecessor_id=pred_id, successor_type=succ_kind,
            successor_id=succ_id, dependency_type=kind, lag_days=lag)
    session.flush()

    for (kind, title, severity, status, owner, description, mitigation,
         target) in spec["raid"]:
        svc.create_raid(
            session, who, pid, raid_type=kind, title=title,
            description=description, severity=severity, status=status,
            owner_id=people[owner], mitigation=mitigation,
            raised_date=_d(today, -20), target_date=_d(today, target))
    session.flush()

    return pid, {"workstreams": len(streams), "tasks": len(tasks),
                 "milestones": len(stones),
                 "dependencies": len(spec["dependencies"]),
                 "raid": len(spec["raid"]),
                 "participants": len(spec["participants"])}


def _history(session: Any, who: Any, people: dict[str, int], pid: int,
             spec: dict[str, Any], today: date) -> int:
    """A fortnight of updates behind the plan.

    A project whose every row was written this morning reads as a fixture.
    What makes one look real is a history in which somebody said something
    four days ago and has not said anything since — which is also exactly what
    the staleness rule is for, so this is not decoration.
    """
    from backend.models.planner import ENTITY_TASK
    from backend.planner import service as svc

    said = 0
    for (code, title, _ws, _parent, owner, status, percent, _start, _due,
         _weight, _critical, blocked, blocker, next_step) in spec["tasks"]:
        if status not in ("IN_PROGRESS", "IN_REVIEW"):
            continue
        narrative = next_step or f"{title} is under way."
        if blocked and blocker:
            narrative = f"Blocked: {blocker}"
        svc.record(
            session, pid, entity_type=ENTITY_TASK, entity_id=None,
            entity_code=code, action="progress",
            author_id=people[owner], source="UI",
            old_percent=max(percent - 20, 0), new_percent=percent,
            new_status=status, narrative=narrative,
            blocker=blocker, next_step=next_step)
        said += 1
    session.flush()
    return said


def _backdate(session: Any, pid: int, today: date) -> None:
    """Push the history and the tasks' own clocks into the past, together.

    Both, deliberately. Moving the history rows and leaving `last_update_at`
    at "now" produces a plan whose story says a task has been silent for five
    days while the task itself claims it was updated a moment ago — a plan
    that looks healthier than the story it tells, and a chase list that comes
    out empty.
    """
    from datetime import datetime
    from datetime import timedelta as _td

    from sqlalchemy import text

    now = datetime.now()
    for offset, share in ((12, 0.3), (6, 0.3), (3, 0.4)):
        session.execute(text("""
            UPDATE planner_updates
               SET created_at = :when
             WHERE project_id = :pid
               AND id IN (SELECT id FROM planner_updates
                           WHERE project_id = :pid
                             AND created_at > :recent
                           ORDER BY id
                           LIMIT (SELECT GREATEST(1, (COUNT(*) * :share)::int)
                                    FROM planner_updates
                                   WHERE project_id = :pid))
        """), {"pid": pid, "when": now - _td(days=offset),
               "recent": now - _td(minutes=30), "share": share})

    session.execute(text("""
        UPDATE planner_tasks t
           SET last_update_at = latest.at
          FROM (SELECT entity_code, MAX(created_at) AS at
                  FROM planner_updates
                 WHERE project_id = :pid AND entity_type = 'TASK'
                 GROUP BY entity_code) latest
         WHERE t.project_id = :pid AND t.code = latest.entity_code
    """), {"pid": pid})

    # Anything nobody has said a word about has never been updated, which is a
    # different fact from "updated when it was created" and the one the
    # staleness rule should see.
    session.execute(text("""
        UPDATE planner_tasks
           SET last_update_at = NULL
         WHERE project_id = :pid
           AND status = 'NOT_STARTED'
    """), {"pid": pid})


def _remove(session: Any, codes: tuple[str, ...]) -> list[str]:
    """Delete only the programmes named here, and say which."""
    from sqlalchemy import select

    from backend.models.planner import PlannerProject

    gone: list[str] = []
    for row in session.execute(
            select(PlannerProject).where(
                PlannerProject.code.in_(codes))).scalars().all():
        gone.append(row.code)
        session.delete(row)
    session.flush()
    return gone


def _existing(session: Any) -> set[str]:
    from sqlalchemy import select

    from backend.models.planner import PlannerProject

    return set(session.execute(
        select(PlannerProject.code).where(
            PlannerProject.code.in_(CODES))).scalars().all())


def build(*, reset: bool = False, check: bool = False) -> Report:
    from backend.db.engine import get_session
    from backend.planner import control
    from backend.planner import query as pq

    report = Report()
    today = date.today()

    if reset:
        allowed, why = _may_reset()
        if not allowed:
            report.error = why
            return report
        report.notes.append(f"Reset allowed: {why}")

    with get_session() as session:
        present = _existing(session)
        if check:
            report.built = sorted(present)
            report.skipped = sorted(set(CODES) - present)
            for code in sorted(present):
                report.counts[code] = _counts(session, code)
            return report

        if reset and present:
            report.removed = _remove(session, CODES)
            present = set()

        people = _people(session)

        for spec in programmes(today):
            if spec["code"] in present:
                report.skipped.append(spec["code"])
                continue
            # Built AS its manager, not as one shared seeder. `create_project`
            # makes the creator its owner, and a participant list that then
            # names that same person a contributor would take the creator's
            # own access away half way through building it.
            who = Seeder(people[spec["manager"]])
            pid, counts = _build_one(session, who, people, spec, today)
            counts["updates"] = _history(session, who, people, pid, spec, today)
            _backdate(session, pid, today)
            report.built.append(spec["code"])
            report.counts[spec["code"]] = counts

        # Health is calculated, never set. If the rules change, the colours on
        # the demonstration change with them — which is the point.
        for code in report.built:
            from sqlalchemy import select

            from backend.models.planner import PlannerProject

            row = session.execute(
                select(PlannerProject).where(
                    PlannerProject.code == code)).scalar_one()
            plan = pq.plan_of(session, int(row.id))
            verdict = control.health(plan, today)
            row.calculated_health = verdict.status
            row.calculated_health_reason = verdict.reason
            row.calculated_percent_complete = control.progress(plan.tasks)
            report.health[code] = f"{verdict.status} — {verdict.reason}"

        session.commit()
    return report


def _counts(session: Any, code: str) -> dict[str, int]:
    from sqlalchemy import func, select

    from backend.models.planner import (
        PlannerDependency,
        PlannerMilestone,
        PlannerProject,
        PlannerRaid,
        PlannerTask,
        PlannerWorkstream,
    )

    pid = session.execute(
        select(PlannerProject.id).where(
            PlannerProject.code == code)).scalar_one_or_none()
    if pid is None:
        return {}
    out: dict[str, int] = {}
    for name, model in (("workstreams", PlannerWorkstream),
                        ("tasks", PlannerTask),
                        ("milestones", PlannerMilestone),
                        ("dependencies", PlannerDependency),
                        ("raid", PlannerRaid)):
        out[name] = int(session.execute(
            select(func.count()).select_from(model)
            .where(model.project_id == pid)).scalar() or 0)
    return out


def refresh_dates(*, dry_run: bool = False, force: bool = False,
                  today: date | None = None) -> demo.Refresh:
    """Roll the demonstration's dates forward to today.

    Non-destructive by construction: it moves only the scheduling fields named
    in `demo.FIELDS`, only on projects whose `demo_origin` says CreditProbe
    seeded them, and it deletes nothing. A dry run opens the same transaction
    and rolls it back, so what it prints is what the real run would do rather
    than a separate calculation that could drift from it.
    """
    from backend.db.engine import get_session

    with get_session() as session:
        if dry_run:
            out = demo.plan(session, today=today, force=force)
            session.rollback()
            return out
        out = demo.apply(session, today=today, force=force)
        session.commit()
        return out


def _print_refresh(out: demo.Refresh, *, dry_run: bool) -> None:
    lead = "would move" if dry_run else "moved"
    print(f"  demo dates, as at {out.today}"
          + ("  (dry run — nothing was written)" if dry_run else ""))
    for entry in out.projects:
        if entry.shift_days == 0:
            print(f"  {entry.code}: already anchored to {out.today}. "
                  "Nothing to do.")
            continue
        print(f"  {entry.code}: anchored {entry.anchor}, "
              f"{entry.shift_days:+d} days — {lead} {len(entry.moving)} "
              f"date{'' if len(entry.moving) == 1 else 's'}"
              + (f", held {len(entry.held)}" if entry.held else ""))
        for move in entry.moving[:6]:
            print(f"      {move.entity_type:<9} {move.entity_code:<8} "
                  f"{move.field:<16} {move.before} -> {move.after}")
        if len(entry.moving) > 6:
            print(f"      ... and {len(entry.moving) - 6} more")
        for move in entry.held:
            print(f"      HELD      {move.entity_code:<8} "
                  f"{move.field:<16} {move.before}  ({move.why})")
    for note in out.notes:
        print(f"  note     {note}")
    if out.held and not out.forced:
        print("\n  Dates a person set are preserved. Pass "
              "--force-demo-dates to overwrite them.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report what exists; change nothing")
    parser.add_argument("--reset", action="store_true",
                        help="DESTRUCTIVE, demo/dev only: remove these four "
                             "programmes and rebuild them from scratch")
    parser.add_argument("--refresh-dates", action="store_true",
                        help="roll the demonstration's dates forward to "
                             "today, keeping everything else")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --refresh-dates: print what would move "
                             "and write nothing")
    parser.add_argument("--force-demo-dates", action="store_true",
                        help="with --refresh-dates: also move dates a person "
                             "changed after seeding")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable result")
    args = parser.parse_args()

    if args.refresh_dates:
        try:
            out = refresh_dates(dry_run=args.dry_run,
                                force=args.force_demo_dates)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            message = f"{type(exc).__name__}: {exc}"
            if args.json:
                print(json.dumps({"error": message}, indent=2))
            else:
                print(f"Could not refresh: {message}")
            return EXIT_CANNOT_RUN
        if args.json:
            print(json.dumps(out.to_dict(), indent=2))
        else:
            _print_refresh(out, dry_run=args.dry_run)
        return EXIT_OK

    if args.dry_run or args.force_demo_dates:
        print("--dry-run and --force-demo-dates only mean something with "
              "--refresh-dates.")
        return EXIT_CANNOT_RUN

    try:
        report = build(reset=args.reset, check=args.check)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        report = Report(error=f"{type(exc).__name__}: {exc}")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        if report.error:
            print(f"Could not run: {report.error}")
        for code in report.removed:
            print(f"  removed  {code}")
        for code in report.built:
            counts = report.counts.get(code, {})
            print(f"  built    {code}: "
                  + ", ".join(f"{v} {k}" for k, v in counts.items()))
            print(f"           {report.health.get(code, '')}")
        for code in report.skipped:
            print(f"  present  {code}")
        for note in report.notes:
            print(f"  note     {note}")

    if report.error:
        return EXIT_CANNOT_RUN
    if not args.check and len(report.built) + len(report.skipped) < len(CODES):
        return EXIT_INCOMPLETE
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
