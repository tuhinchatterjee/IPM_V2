"""The demonstration workspace: what a presenter walks through, and the reset.

§9 and §12 of the client-demo release-candidate brief.

The problem this solves
-----------------------
A development database accumulates. By the time this phase opened, the local
platform database held 2,312 Projects — 2,079 of them identically named
"Contracting concentration review" — 4,772 Investigations, 231 Lenses
including "Test lens", 385 Playbooks including "Test appetite check", and ten
user accounts called things like `wf_author`. Every one of those was created
by a passing test and every one of them would have been on screen in front of
a client.

That is not a cosmetic problem. A CRO who sees two thousand identical
Projects concludes, correctly, that nobody has looked at this screen.

So the demonstration runs on a KNOWN state, and `reset()` rebuilds it.

What reset removes, and what it must never touch
------------------------------------------------
The line is between the WORKSPACE — what people did — and the GOVERNED
PLATFORM — what the product knows. Reset rebuilds the first and does not read
the second.

Removed: Projects, Investigations and their messages and versions, saved
Analyses, workflow items and their events, messages and recipients,
notifications, comments, Risk Cases, agent runs and tasks, playbook runs,
Lenses, Playbooks, analysis runs, assurance records, feedback events, learning
observations, grid preferences.

Never touched: the governed datasets, domains, field definitions and
relationships; the teaching library; Regulatory, Teaching and Learning
Releases and their approvals; users' credentials; Alembic's version table;
anything in `data/`; and the `.env`.

Two of those deserve their reason stated. **Approved releases stay** because
an approval is a person's recorded decision and a demo reset is not a licence
to erase one. **Assurance records go**, even though they are immutable, for
exactly the same reason they are immutable: each one is bound to the analysis
run that produced it, and keeping the record after deleting the run leaves an
Assurance verdict about nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

WORKSPACE_VERSION = "1.0.0"

#: The period the demonstration is pinned to, and the one before it. Fixed so
#: that "compare with four quarters ago" means the same thing every time the
#: demonstration is run.
PERIOD = "Q2 2026"
PRIOR_PERIOD = "Q1 2026"

#: Marks an object as belonging to the demonstration. Written into the JSONB
#: context Projects and Investigations already carry, so reset can rebuild
#: what it owns without a schema change and without guessing from names.
MARK = "creditprobe_demo"

#: Tables emptied by a reset, in the order they must be emptied so a foreign
#: key never blocks a delete. Children before parents, always.
#:
#: Stated as a list of table names rather than derived from the metadata
#: graph, because "which tables does a demo reset own" is a JUDGEMENT about
#: what is workspace and what is governed platform, and a topological sort
#: cannot make it. Anything not on this list survives a reset.
RESET_ORDER: tuple[str, ...] = (
    # feedback and learning: observations of the demo conversation
    "learning_observations",
    "feedback_events",
    # workflow, deepest first
    "workflow_recipients",
    "workflow_messages",
    "workflow_events",
    "workflow_items",
    "comments",
    "notifications",
    # risk cases reference agent runs and investigations
    "risk_cases",
    "agent_events",
    "agent_tasks",
    "agent_runs",
    # dashboards and standing instructions
    "playbook_runs",
    "playbooks",
    "lens_revisions",
    "lenses",
    # the analytical record
    "assurance_records",
    "saved_analyses",
    "investigation_versions",
    "investigation_messages",
    "investigations",
    "project_status_events",
    "projects",
    "analysis_runs",
    # per-user presentation state
    "grid_preferences",
)

#: Tables a reset must never empty, checked rather than trusted. If a table
#: appears in both lists the reset refuses to run: that is a programming
#: mistake, and the moment to catch it is before the DELETE, not after.
PROTECTED_TABLES: frozenset[str] = frozenset({
    "alembic_version",
    "users", "teams", "team_members",
    "data_domains", "dataset_definitions", "field_definitions",
    "dataset_relationships", "dataset_relationship_versions",
    "teaching_cases", "teaching_case_events",
    "teaching_releases", "regulatory_documents", "regulatory_releases",
    "learning_releases", "learning_release_activations",
    "learning_review_decisions", "candidate_learning_cases",
    "local_training_runs", "replay_runs",
    "studio_methods",
    "ai_validation_cases", "ai_validation_runs",
    "agent_policies", "agent_workers",
})

#: Accounts the test suite creates. Removed only when a reset is asked to
#: include users, and named exactly rather than matched by a pattern: a
#: pattern that removed a real account because it happened to start with
#: "wf_" would be a far worse failure than leaving one test row on screen.
TEST_ACCOUNTS: tuple[str, ...] = (
    "gridpref.one", "gridpref.two", "gatecheck.steward",
    "hier_author", "hier_reviewer",
    "wf_author", "wf_reviewer", "wf_sender", "wf_first", "wf_second",
)

#: The four accounts the demonstration is given to a client on. Kept in step
#: with `scripts/seed_demo_users.py`, which owns their creation.
DEMO_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("alex.rahman", "ADMIN", "Administrator"),
    ("sara.qahtani", "DATA_STEWARD", "Data Steward"),
    ("omar.nasser", "ANALYST", "Analyst, and the workflow reviewer"),
    ("layla.haddad", "VIEWER", "Viewer"),
)


@dataclass
class Change:
    """One table a reset touched, and how many rows went."""

    table: str
    rows: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"table": self.table, "rows": self.rows, "error": self.error}


@dataclass
class Result:
    """What a reset or a seed did. Reported whole, including the failures."""

    action: str = ""
    preview: bool = False
    changes: list[Change] = field(default_factory=list)
    created: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def rows(self) -> int:
        return sum(c.rows for c in self.changes)

    @property
    def ok(self) -> bool:
        return not self.error and not any(c.error for c in self.changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "preview": self.preview,
            "rows": self.rows,
            "changes": [c.to_dict() for c in self.changes],
            "created": dict(self.created),
            "notes": list(self.notes),
            "error": self.error,
            "ok": self.ok,
            "version": WORKSPACE_VERSION,
        }


class DemoError(Exception):
    """A reset or seed refused."""


def _check_lists() -> None:
    """A table may not be both reset and protected.

    Run before every reset rather than once at import, so a later edit that
    introduces the overlap is caught by the next run rather than by whoever is
    presenting.
    """
    both = sorted(set(RESET_ORDER) & PROTECTED_TABLES)
    if both:
        raise DemoError(
            "the reset list and the protected list both name: "
            + ", ".join(both)
            + " — one of them is wrong, and a reset will not run until it is "
              "settled")


def counts(session: Any) -> dict[str, int]:
    """How many rows each resettable table holds. Used by preview and check."""
    from sqlalchemy import text

    found: dict[str, int] = {}
    for table in RESET_ORDER:
        try:
            found[table] = int(session.execute(
                text(f"SELECT count(*) FROM {table}")).scalar() or 0)
        except Exception:  # noqa: BLE001 - a table that is not there is zero
            session.rollback()
            found[table] = 0
    return found


def reset(session: Any, *, preview: bool = False,
          include_users: bool = False) -> Result:
    """Rebuild the demonstration workspace to nothing, ready for a seed.

    `preview` counts what WOULD go and changes nothing — §9's `-WhatIf`. The
    same code path produces both, so a preview cannot describe a different
    delete from the one that runs.
    """
    _check_lists()
    from sqlalchemy import text

    result = Result(action="reset", preview=preview)
    before = counts(session)
    for table in RESET_ORDER:
        rows = before.get(table, 0)
        if preview:
            result.changes.append(Change(table=table, rows=rows))
            continue
        try:
            session.execute(text(f"DELETE FROM {table}"))
            result.changes.append(Change(table=table, rows=rows))
        except Exception as e:  # noqa: BLE001
            session.rollback()
            result.changes.append(
                Change(table=table, rows=0, error=str(e)[:200]))

    if include_users:
        result.notes.append(_remove_test_accounts(session, result,
                                                  preview=preview))
    else:
        result.notes.append(
            "Test accounts were left alone. Pass include_users to remove "
            f"the {len(TEST_ACCOUNTS)} accounts the test suite creates.")

    if not preview and result.ok:
        session.commit()
    elif not preview:
        session.rollback()
        result.error = "one or more tables refused to empty; nothing was kept"
    return result


def _remove_test_accounts(session: Any, result: Result, *,
                          preview: bool) -> str:
    from sqlalchemy import select

    from backend.db.models import User

    rows = session.execute(
        select(User).where(User.username.in_(TEST_ACCOUNTS))).scalars().all()
    names = sorted(u.username for u in rows)
    if not preview:
        for row in rows:
            session.delete(row)
    result.changes.append(Change(table="users", rows=len(rows)))
    if not names:
        return "No test accounts were present."
    return (f"{'Would remove' if preview else 'Removed'} "
            f"{len(names)} test account(s): {', '.join(names)}.")


def residue(session: Any) -> list[str]:
    """Signs that this database is a development database, not a demo one.

    Checked by `demo-check` and reported as a FAIL, because every one of these
    is something a client would see. Named exactly, so the check says what to
    do rather than that something is wrong.
    """
    from sqlalchemy import func, select

    from backend.db.models import User
    from backend.models.platform import Lens, Playbook, Project

    found: list[str] = []

    duplicates = session.execute(
        select(Project.name, func.count())
        .group_by(Project.name)
        .having(func.count() > 3)
        .order_by(func.count().desc())).all()
    for name, how_many in duplicates:
        found.append(f"{how_many} Projects share the name {name!r} — a test "
                     "suite created them, and a client would see every one")

    for model, label in ((Lens, "Lens"), (Playbook, "Playbook")):
        rows = session.execute(
            select(model.name).where(model.name.ilike("test%"))).scalars().all()
        for name in sorted(set(rows)):
            found.append(f"{label} named {name!r} is test residue")

    accounts = session.execute(
        select(User.username)
        .where(User.username.in_(TEST_ACCOUNTS))).scalars().all()
    if accounts:
        found.append(f"{len(accounts)} test account(s) are present: "
                     + ", ".join(sorted(accounts)))
    return found
