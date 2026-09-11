#!/usr/bin/env python
"""Remove automated-test leftovers from a DEVELOPMENT database.

A test run that is interrupted before its teardown leaves its fixtures
behind, and a development database that has hosted a few hundred runs stops
resembling the product: on this deployment the Project Planner opened on
**1,993 projects and 2,525 attention items**, none of which a person had
created, and every one of them called something like "Actions fixture" or
"Permission fixture project". Nobody can do UAT against that, and nobody can
judge whether the screen is well designed when the screen is full of noise.

This removes exactly two things, both identified by names no real record
uses:

  * **fixture accounts** — `esc-<tag>-NNNNN`, `z.escalation-<tag>`,
    `proof-<tag>-NNNNN`, `z.proof-<tag>`: the eight-thousand-person crowds
    the directory-scale tests and the directory acceptance script create;
  * **fixture projects** — every planner project whose code is not one of
    the demo programmes the bootstrap seeds.

It refuses to run against anything but a development environment, prints
what it is about to do, and does nothing at all without `--apply`.

    python scripts/clean_test_fixtures.py            # say what would go
    python scripts/clean_test_fixtures.py --apply    # actually remove it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: The planner projects a deployment is SUPPOSED to have. Everything else in
#: a development database is a test fixture: the demo bootstrap seeds these
#: and nothing else creates a project without a person pressing Publish.
DEMO_PROJECT_CODES = {
    "IFRS9-REDEV",       # scripts/seed_planner.py
    "RET-IFRS9",         # scripts/seed_retail_portfolio.py …
    "RET-SCORECARD",
    "RET-COLLECTIONS",
    "RET-DATA-REM",
}

#: Username shapes that only ever belong to a test crowd.
FIXTURE_USER_PATTERNS = ("esc-%", "z.escalation-%", "proof-%", "z.proof-%")


def _accounts(session: Any) -> list[int]:
    from sqlalchemy import or_, select

    from backend.db.models import User

    where = or_(*[User.username.like(p) for p in FIXTURE_USER_PATTERNS])
    return [int(row) for row in session.execute(
        select(User.id).where(where)).scalars()]


def _projects(session: Any) -> tuple[list[int], list[str]]:
    from sqlalchemy import select

    from backend.models.planner import PlannerProject

    rows = session.execute(
        select(PlannerProject.id, PlannerProject.code)).all()
    drop = [int(r[0]) for r in rows if (r[1] or "") not in DEMO_PROJECT_CODES]
    kept = sorted((r[1] or "") for r in rows
                  if (r[1] or "") in DEMO_PROJECT_CODES)
    return drop, kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="actually delete; without it nothing is written")
    args = parser.parse_args()

    from sqlalchemy import text

    from backend.config import settings
    from backend.db.engine import get_session

    where = str(getattr(settings, "env", "")).lower()
    if where not in {"dev", "development", "test", "local"}:
        print(f"environment is {where!r}: refusing to run. "
              "This is a development-database tool.")
        return 2

    with get_session() as session:
        people = _accounts(session)
        drop, kept = _projects(session)
        print(f"fixture accounts : {len(people):,}")
        print(f"fixture projects : {len(drop):,}")
        print(f"demo projects kept: {kept or '(none seeded)'}")
        if not args.apply:
            print("\nNothing was changed. Re-run with --apply to remove them.")
            return 0

        if people:
            # Signing in is an audited act, and audit references the actor.
            session.execute(
                text("DELETE FROM collaboration_audit "
                     "WHERE actor_id = ANY(:i)"), {"i": people})
            session.execute(text("DELETE FROM users WHERE id = ANY(:i)"),
                            {"i": people})
        if drop:
            # planner_drafts holds the project it published into with
            # RESTRICT rather than CASCADE, so the draft goes first.
            session.execute(
                text("DELETE FROM planner_drafts WHERE project_id = ANY(:i)"),
                {"i": drop})
            session.execute(
                text("DELETE FROM planner_projects WHERE id = ANY(:i)"),
                {"i": drop})
        # Unpublished drafts. On a development database every one of these is
        # a journey script that stopped half way; on a real one they would be
        # somebody's unfinished plan, which is why this tool refuses to run
        # anywhere but development.
        session.execute(text("DELETE FROM planner_drafts "
                             "WHERE project_id IS NULL"))
        session.commit()

        left = session.execute(
            text("SELECT count(*) FROM planner_projects")).scalar()
        drafts = session.execute(
            text("SELECT count(*) FROM planner_drafts")).scalar()
        users = session.execute(text("SELECT count(*) FROM users")).scalar()
        print(f"\nremoved. planner projects now {left}, drafts {drafts}, "
              f"accounts {users:,}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
