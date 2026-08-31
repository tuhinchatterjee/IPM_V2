#!/usr/bin/env python
"""Bring a CreditProbe deployment to a demonstrable state, once.

    python scripts/bootstrap_demo.py            do whatever is missing
    python scripts/bootstrap_demo.py --check    report only; change nothing
    python scripts/bootstrap_demo.py --step corporate --force
    python scripts/bootstrap_demo.py --json     machine-readable result
    python scripts/bootstrap_demo.py --marker PATH   write the verdict to a file

Machine-readable output and human progress do not share a stream
----------------------------------------------------------------
The builders this script calls narrate what they are doing — "> Building the
corporate universe", "16 quarter(s)", "> Deriving the graph". They print, and
before this they printed onto the same stdout that `--json` was supposed to
own. A fresh Mac's `docker compose up` therefore wrote a readiness marker that
began with prose, `json.loads` failed with "Expecting value: line 1 column 1",
the container never went healthy, the frontend never started because it
depends on backend health, and localhost:3000 refused the connection. The API
itself was fine the whole time.

Two things stop that recurring, and both are here because either alone leaves
a way back in:

  --json    redirects narration to stderr for the duration of the run, so
            stdout carries exactly one thing: the JSON document.
  --marker  writes the verdict straight to a file from the structured result,
            never through a stream at all. This is what the entrypoint uses,
            so no amount of printing anywhere — including from a future step
            that shells out and writes to file descriptor 1 — can corrupt it.

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
import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import bootstrap  # noqa: E402

EXIT_OK = 0
EXIT_NOT_READY = 1
EXIT_CANNOT_RUN = 2


def _write_marker(result_or_report, path: str) -> None:
    """Write the verdict to `path`, atomically, from the structured result.

    Atomically because the health check reads this file on a timer and a
    half-written document is an unparseable one — which is the same failure
    under a different cause. Written into the destination's own directory so
    the replace is a rename within one filesystem rather than a copy.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    verdict = dict(result_or_report.to_dict())
    # One key means one thing to the health check. `run()` reports `ok`;
    # `verify()` reports `ready`. The marker always carries `ok`, so the
    # health check never has to know which of the two produced it.
    if "ok" not in verdict:
        verdict["ok"] = bool(verdict.get("ready"))
    body = json.dumps(verdict, indent=2)
    handle, temporary = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(body)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


@contextlib.contextmanager
def _narration_off_stdout(active: bool):
    """Send everything printed during the run to stderr instead.

    `contextlib.redirect_stdout` rebinds `sys.stdout` for the whole process,
    so a builder calling the bare `print()` builtin lands on stderr without
    knowing anything about this script. It does not cover a subprocess writing
    to file descriptor 1 — nothing at Python level does — which is why the
    marker is written to a file rather than parsed back off this stream.
    """
    if not active:
        yield
        return
    with contextlib.redirect_stdout(sys.stderr):
        yield


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
    parser.add_argument("--json", action="store_true",
                        help="stdout carries the JSON result and nothing else")
    parser.add_argument("--marker", default="",
                        help="write the JSON result to this file as well")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    # stderr, explicitly. Progress is not the result, and a reader piping this
    # script into `json.loads` should never receive a word of it.
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s", stream=sys.stderr)

    if args.list:
        for step in bootstrap.steps():
            print(f"  {step.letter}  {step.key:<15} {step.title}")
        return EXIT_OK

    quiet_stdout = args.json or bool(args.marker)

    if args.check:
        from backend.config import settings

        with _narration_off_stdout(quiet_stdout):
            if settings.has_database:
                from backend.db.engine import get_session

                with get_session() as session:
                    report = bootstrap.verify(session)
            else:
                report = bootstrap.verify(None)
        if args.marker:
            _write_marker(report, args.marker)
        _print(report, as_json=args.json)
        return EXIT_OK if report.ready else EXIT_NOT_READY

    with _narration_off_stdout(quiet_stdout):
        result = bootstrap.run(only=args.step, force=args.force,
                               skip_builders=args.skip_builders)
    if args.marker:
        _write_marker(result, args.marker)
    _print(result, as_json=args.json)
    if args.step:
        # One step was asked for, so the whole-deployment verdict is not the
        # question. Report on the step, not on everything it did not touch.
        return EXIT_OK if not result.failed else EXIT_NOT_READY
    return EXIT_OK if result.ok else EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
