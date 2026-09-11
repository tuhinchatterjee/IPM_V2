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

  * **fixture accounts** — three shapes, none of which a person can create
    through the product: an account whose stored password is the literal
    `x` (no hashing function produces that, and every test that builds a
    User by hand writes it), an account named `<letter>.<12 hex digits>`,
    and the named crowds the directory-scale tests build. On this
    deployment that was **9,617 of 9,651 accounts**, which is why the
    sponsor picker offered "Showing 50 of 9,441 matches" and every one of
    the first fifty was called "Alice Test";
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

#: A username of the form `t.3f5aac1ebbab` — one letter, a dot, and a slice
#: of a uuid4. Nobody types that; the shared test helpers generate it.
FIXTURE_USER_SHAPE = r"^[a-z]\.[0-9a-f]{12}$"

#: The literal stored in `password_hash` by every test that constructs a
#: `User` directly rather than going through registration. A real account
#: cannot hold it: a hash is always long, and one character never verifies.
FIXTURE_PASSWORD_HASH = "x"

#: Every column anywhere in the schema that names a person and would
#: REFUSE to let that person go. Columns declared `ON DELETE CASCADE` or
#: `SET NULL` look after themselves; these do not, so the rows they belong
#: to — a message the crowd sent, an investigation it owned, the audit of
#: its own sign-ins — have to go first. Asking the database which columns
#: those are is more honest than keeping a hand-written list that silently
#: falls behind the next migration.
BLOCKING_COLUMNS = """
SELECT tc.table_name, kcu.column_name
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
  JOIN information_schema.constraint_column_usage ccu
    ON tc.constraint_name = ccu.constraint_name
  JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
 WHERE tc.constraint_type = 'FOREIGN KEY'
   AND ccu.table_name = 'users'
   AND ccu.column_name = 'id'
   AND rc.delete_rule IN ('NO ACTION', 'RESTRICT')
"""

#: How many times to go round the blocking tables. One table can hold
#: another up — an artefact attached to a message the same crowd sent — so
#: a table that refuses is simply tried again on the next pass, once the
#: thing that was holding it has gone.
PASSES = 8


def _blocking(session: Any) -> list[tuple[str, tuple[str, ...]]]:
    from sqlalchemy import text

    grouped: dict[str, set[str]] = {}
    for table, column in session.execute(text(BLOCKING_COLUMNS)).all():
        grouped.setdefault(str(table), set()).add(str(column))
    return [(table, tuple(sorted(columns)))
            for table, columns in sorted(grouped.items())]


def _sweep(session: Any, people: list[int]) -> None:
    """Remove what the fixture crowd wrote, then the crowd itself."""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    pending = _blocking(session)
    for _ in range(PASSES):
        refused: list[tuple[str, tuple[str, ...]]] = []
        for table, columns in pending:
            clause = " OR ".join(f"{c} = ANY(:i)" for c in columns)
            try:
                with session.begin_nested():
                    session.execute(
                        text(f"DELETE FROM {table} WHERE {clause}"),
                        {"i": people})
            except IntegrityError:
                refused.append((table, columns))
        if not refused:
            break
        if refused == pending:
            raise RuntimeError(
                "these tables refuse to release the fixture accounts and "
                "nothing else is holding them: "
                + ", ".join(t for t, _ in refused))
        pending = refused
    session.execute(text("DELETE FROM users WHERE id = ANY(:i)"),
                    {"i": people})


def _accounts(session: Any) -> list[int]:
    from sqlalchemy import or_, select

    from backend.db.models import User

    where = or_(
        User.password_hash == FIXTURE_PASSWORD_HASH,
        User.username.op("~")(FIXTURE_USER_SHAPE),
        *[User.username.like(p) for p in FIXTURE_USER_PATTERNS],
    )
    return [int(row) for row in session.execute(
        select(User.id).where(where)).scalars()]


def _real(session: Any) -> list[str]:
    """The accounts this will keep, so a reviewer can see them by name."""
    from sqlalchemy import or_, select

    from backend.db.models import User

    where = or_(
        User.password_hash == FIXTURE_PASSWORD_HASH,
        User.username.op("~")(FIXTURE_USER_SHAPE),
        *[User.username.like(p) for p in FIXTURE_USER_PATTERNS],
    )
    return sorted(str(name) for name in session.execute(
        select(User.username).where(~where)).scalars())


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
        keeping = _real(session)
        print(f"fixture accounts : {len(people):,}")
        print(f"fixture projects : {len(drop):,}")
        print(f"demo projects kept: {kept or '(none seeded)'}")
        print(f"accounts kept    : {len(keeping)} — "
              + ", ".join(keeping[:25])
              + (" …" if len(keeping) > 25 else ""))
        if not args.apply:
            print("\nNothing was changed. Re-run with --apply to remove them.")
            return 0

        if people:
            _sweep(session, people)
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
