#!/usr/bin/env python
"""The demonstration workspace, from the command line.

    python scripts/demo_state.py --check       what is there, and is it clean
    python scripts/demo_state.py --preview     what a reset would remove
    python scripts/demo_state.py --reset       remove it (asks first)
    python scripts/demo_state.py --seed        build the demo workspace
    python scripts/demo_state.py --rebuild     reset, then seed

This is what `demo-reset.ps1` runs inside the backend container, so the
Windows script stays a thin wrapper and the behaviour it wraps is tested here
rather than in PowerShell.

Destructive by design, and it says so. `--reset` and `--rebuild` refuse to run
without either an interactive `yes` or `--yes`, because §4 requires every
destructive action to be confirmed and a script that deletes 47,000 rows on a
typo is not a demonstration aid.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.demo import mode, seed  # noqa: E402
from backend.demo import workspace as ws  # noqa: E402

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_REFUSED = 3


def _confirm(what: str, rows: int, *, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print(f"REFUSED: {what} would remove {rows:,} rows and there is no "
              "terminal to confirm at. Pass --yes if that is what you mean.")
        return False
    print(f"This will remove {rows:,} rows from the demonstration workspace.")
    print("Governed data, the teaching library, approved releases and user "
          "credentials are NOT touched.")
    return input("Type 'yes' to continue: ").strip().lower() == "yes"


def _check(session) -> int:
    posture = mode.posture()
    print(posture.sentence())
    print()
    found = ws.counts(session)
    live = {t: n for t, n in found.items() if n}
    print(f"Workspace: {sum(found.values()):,} rows across "
          f"{len(live)} populated table(s).")
    for table, rows in sorted(live.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {rows:>8,}  {table}")

    problems = ws.residue(session)
    print()
    if problems:
        print(f"RESIDUE: {len(problems)} sign(s) that this is a development "
              "database, not a demonstration one:")
        for line in problems:
            print(f"  - {line}")
        print()
        print("Run:  python scripts/demo_state.py --rebuild --yes")
        return EXIT_PROBLEM
    print("No test residue found.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--preview", action="store_true")
    action.add_argument("--reset", action="store_true")
    action.add_argument("--seed", action="store_true")
    action.add_argument("--rebuild", action="store_true")
    parser.add_argument("--yes", action="store_true",
                        help="skip the confirmation prompt")
    parser.add_argument("--include-users", action="store_true",
                        help="also remove the accounts the test suite creates")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from backend.db.engine import get_session

    with get_session() as session:
        if args.check:
            return _check(session)

        if args.preview:
            found = ws.reset(session, preview=True,
                             include_users=args.include_users)
            if args.json:
                print(json.dumps(found.to_dict(), indent=2))
            else:
                print(f"A reset would remove {found.rows:,} rows.")
                for change in found.changes:
                    if change.rows:
                        print(f"    {change.rows:>8,}  {change.table}")
                for note in found.notes:
                    print(f"  note: {note}")
            return EXIT_OK

        if args.reset or args.rebuild:
            planned = ws.reset(session, preview=True,
                               include_users=args.include_users)
            if not _confirm("a reset", planned.rows, yes=args.yes):
                return EXIT_REFUSED
            done = ws.reset(session, include_users=args.include_users)
            print(f"Removed {done.rows:,} rows.")
            for note in done.notes:
                print(f"  note: {note}")
            if not done.ok:
                print(f"  PROBLEM: {done.error}")
                return EXIT_PROBLEM

        if args.seed or args.rebuild:
            built = seed.build(session)
            if built.error:
                print(f"SEED FAILED: {built.error}")
                return EXIT_PROBLEM
            print("Seeded the demonstration workspace:")
            for what, how_many in sorted(built.created.items()):
                print(f"    {how_many:>4}  {what}")
            for note in built.notes:
                print(f"  note: {note}")
            if args.json:
                print(json.dumps(built.to_dict(), indent=2))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
