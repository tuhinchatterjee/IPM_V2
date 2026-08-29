#!/usr/bin/env python
"""
Load the teaching corpus into the governed library. §13.

    .venv/bin/python scripts/seed_teaching_library.py            # load
    .venv/bin/python scripts/seed_teaching_library.py --report    # count only

What it does and, more importantly, what it does not
-----------------------------------------------------
It writes cases at whatever status their own validators allow, and it stops
there. Nothing is approved, because approval needs a person and §5 is explicit
that a validator passing is not a review. A freshly seeded library therefore
retrieves NOTHING, which is correct: the cases exist, and a reviewer decides
which of them the model gets to see.

Re-running is safe. A case whose stored fingerprint already matches is left
alone rather than written as a new version — otherwise every run would bump
every case, and the version history that exists to make an approval meaningful
would fill with changes nobody made.
"""

from __future__ import annotations

# ruff: noqa: E402 - the repository root has to be on sys.path before the
# backend package can be imported, and the seeding entry point is run as a
# script rather than through an installed console script.
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db.engine import SessionLocal
from backend.services import teaching_library as tl
from backend.teaching import schema as sc
from intelligence_factory.teaching import (
    canonical,
    judgment_blueprints,
    migrate,
    safety,
)


def corpus() -> list[sc.TeachingCase]:
    """Every case the factory offers the library."""
    return [*migrate.cases(), *canonical.cases(),
            *judgment_blueprints.cases(), *safety.cases()]


def seed(*, actor: str = "seed") -> dict[str, int]:
    counts = {"written": 0, "unchanged": 0, "failed": 0}
    session = SessionLocal()
    try:
        for case in corpus():
            existing = tl.latest(session, case.case_id)
            # The whole body, not just the fingerprint. A fingerprint covers
            # what a case TEACHES, which is deliberately narrower than what a
            # case IS: correcting an authoring method or a provenance changes
            # nothing about the lesson and everything about the governance
            # report, and a check that ignored it would leave the library
            # describing itself wrongly for ever.
            if existing is not None and existing.body == case.to_dict():
                counts["unchanged"] += 1
                continue
            try:
                tl.save(session, case, actor=actor)
                counts["written"] += 1
            except tl.LibraryError as error:
                print(f"  ! {case.case_id}: {error}", file=sys.stderr)
                counts["failed"] += 1
        session.commit()
    finally:
        session.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true",
                        help="print what the corpus contains and write "
                             "nothing")
    args = parser.parse_args(argv)

    if args.report:
        print(json.dumps({"migrated": migrate.report(),
                          "canonical": canonical.report(),
                          "judgment": judgment_blueprints.report()},
                         indent=2, sort_keys=True))
        return 0

    counts = seed()
    print(json.dumps(counts, indent=2))

    session = SessionLocal()
    try:
        print(json.dumps(tl.summary(session), indent=2, sort_keys=True))
    finally:
        session.close()
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
