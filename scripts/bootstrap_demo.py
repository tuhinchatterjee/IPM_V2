#!/usr/bin/env python
"""Bring a CreditProbe deployment to a demonstrable state, once.

    python scripts/bootstrap_demo.py            do whatever is missing
    python scripts/bootstrap_demo.py --check    report only; change nothing
    python scripts/bootstrap_demo.py --step corporate --force
    python scripts/bootstrap_demo.py --json     machine-readable result

This is what `docker/backend-entrypoint.sh` runs, and it is the only thing it
runs. A presenter on a fresh machine should never be asked to run a Python
build script; if this script is ever named on a screen, that screen is the
defect.

Exit codes
----------
    0   ready
    1   a required step failed, or a readiness check did not pass
    2   nothing could run (no database, no writable data directory)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import bootstrap  # noqa: E402

EXIT_OK = 0
EXIT_NOT_READY = 1
EXIT_CANNOT_RUN = 2


def _print(result_or_report, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result_or_report.to_dict(), indent=2))
        return
    body = result_or_report.to_dict()
    for step in body.get("steps", []):
        mark = {"DONE": "  +", "SKIPPED": "  .", "FAILED": "  X"}.get(
            step["status"], "  ?")
        print(f"{mark} {step['title']}: {step['detail']}")
    report = body.get("readiness") or body
    if report and report.get("checks"):
        print()
        for check in report["checks"]:
            mark = {"OK": "  +", "MISSING": "  X", "UNKNOWN": "  ?"}.get(
                check["status"], "  ?")
            print(f"{mark} {check['title']}: {check['detail']}")
            if check["status"] != "OK" and check.get("remedy"):
                print(f"      remedy: {check['remedy']}")
    print()
    print(body.get("sentence") or report.get("sentence") or "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report readiness and change nothing")
    parser.add_argument("--step", default="",
                        help="run one step by key (see --list)")
    parser.add_argument("--list", action="store_true",
                        help="list the steps in order")
    parser.add_argument("--force", action="store_true",
                        help="run a step even if it looks already done")
    parser.add_argument("--skip-builders", action="store_true",
                        help="leave the three data universes alone")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s")

    if args.list:
        for step in bootstrap.steps():
            print(f"  {step.letter}  {step.key:<15} {step.title}")
        return EXIT_OK

    if args.check:
        from backend.config import settings

        if settings.has_database:
            from backend.db.engine import get_session

            with get_session() as session:
                report = bootstrap.readiness(session)
        else:
            report = bootstrap.readiness(None)
        _print(report, as_json=args.json)
        return EXIT_OK if report.ready else EXIT_NOT_READY

    result = bootstrap.run(only=args.step, force=args.force,
                           skip_builders=args.skip_builders)
    _print(result, as_json=args.json)
    if args.step:
        # One step was asked for, so the whole-deployment verdict is not the
        # question. Report on the step, not on everything it did not touch.
        return EXIT_OK if not result.failed else EXIT_NOT_READY
    return EXIT_OK if result.ok else EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
