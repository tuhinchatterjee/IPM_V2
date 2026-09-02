#!/usr/bin/env python
"""The protected regression baseline: behaviour that has already been fixed.

Why this file exists
--------------------
Each development phase adds capability, and the failure that costs the most is
never the new thing not working — it is the new thing working while something
already paid for quietly stops. That failure is cheap to find on the night it
happens and expensive to find a week later, by which point nobody remembers
which change did it.

So this is the list of behaviour that must not regress, grouped by the promise
it keeps rather than by the directory it lives in. It runs in one process, in a
few minutes, and is meant to be run THREE times around any significant change:

    python scripts/protected_baseline.py            # before, for a baseline
    python scripts/protected_baseline.py            # after each phase
    python scripts/protected_baseline.py --json out.json   # on the final HEAD

A group that was already red before a change is not that change's fault, and
recording the before-state is the only way to say so honestly. `--json` writes
the result so a later run can be compared against it rather than remembered.

This is deliberately NOT the full suite. The full suite is the gate before a
release; this is the gate around an edit, and a gate nobody has time to run is
a gate that does not exist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: (group, why it is protected, test paths)
#:
#: The "why" is not decoration. When one of these goes red at two in the
#: morning, the person reading the output needs to know what the product
#: promised, not which file failed.
GROUPS: list[tuple[str, str, list[str]]] = [
    (
        "messaging",
        "A message reaches Sent and Inbox; a self-send reaches both; a "
        "request stays a message; attachments carry their share grants.",
        [
            "tests/api/test_messaging.py",
            "tests/api/test_messaging_corrections.py",
            "tests/api/test_message_attachments.py",
            "tests/api/test_message_workflow.py",
            "tests/api/test_workflow_seed.py",
        ],
    ),
    (
        "system-messages",
        "CreditProbe is a governed sender, not an account: its messages land "
        "in the Inbox, count as unread, and carry no provider branding.",
        ["tests/api/test_system_messages.py"],
    ),
    (
        "attention-counts",
        "One authoritative unread count. Reading a message moves every badge "
        "at once, 3 to 2 to 1 to 0, and the two header badges stay disjoint.",
        ["tests/api/test_messaging_corrections.py::TestReadingMovesTheNumber",
         "tests/api/test_messaging_corrections.py::TestOneSummaryReconcilesWithTheBoxes",
         "tests/api/test_messaging_corrections.py::TestTheTwoHeaderBadgesDoNotOverlap"],
    ),
    (
        "permissions",
        "Participation is authorization. A stranger cannot read a thread, a "
        "draft, or an attachment by guessing an id, and an administrator does "
        "not become a participant by being an administrator.",
        [
            "tests/api/test_messaging_security.py",
            "tests/api/test_login_required.py",
            "tests/api/test_named_permissions.py",
            "tests/api/test_user_administration.py",
        ],
    ),
    (
        "admin-workflow",
        "Workflow is administrator-only oversight in counts. Non-admins are "
        "refused at the route, not merely hidden from in the navigation.",
        ["tests/api/test_messaging_corrections.py::TestWorkflowOversight"],
    ),
    (
        "single-period-population",
        "'Show Stage 2 borrowers' returns borrowers at one period. A level "
        "condition is a population, not a two-period cohort, and no measure "
        "is required to return entities.",
        ["tests/orchestration/test_single_period_population.py"],
    ),
    (
        "stage-widening",
        "'Stage 2 or worse' is stage >= 2 under ordered-stage semantics, and "
        "the scope line says so in words.",
        ["tests/orchestration/test_stage_widening.py",
         "tests/orchestration/test_spoken_filters.py"],
    ),
    (
        "movement-vocabulary",
        "'How has ECL moved' is measure movement; 'moved to Stage 3' is "
        "migration. The two must not collapse into each other.",
        ["tests/orchestration/test_movement_vocabulary.py"],
    ),
    (
        "context-carry-forward",
        "Sector, borrower, population, period and filters survive the next "
        "turn, so a follow-up question does not restart the conversation.",
        ["tests/api/test_context_carry_forward.py",
         "tests/orchestration/test_population_context.py",
         "tests/orchestration/test_scope_inheritance.py"],
    ),
    (
        "ordinal-reference",
        "'The second one' resolves to the second row of the result actually "
        "on screen.",
        ["tests/orchestration/test_ordinal_reference.py"],
    ),
    (
        "answer-grain",
        "A question about sectors returns sector rows. The head noun decides "
        "the grain, never the dataset's convenience.",
        ["tests/orchestration/test_grain.py",
         "tests/orchestration/test_dimension_resolution.py"],
    ),
    (
        "multi-condition",
        "AND, OR, NOT and nesting all survive planning, and every predicate "
        "the question asked for is provable on the rows returned.",
        ["tests/orchestration/test_multi_condition.py",
         "tests/orchestration/test_query_fidelity.py"],
    ),
    (
        "ecl-decomposition",
        "The ECL bridge stays multi-step, reconciled and drillable. It must "
        "never collapse to a single number.",
        ["tests/ifrs9/test_ecl_decomposition.py",
         "tests/api/test_ecl_decomposition.py",
         "tests/orchestration/test_decomposition.py"],
    ),
    (
        "cockpit",
        "Three suggestions from the approved five, and a greeting that is "
        "presentation only — never identity, never authorization.",
        ["tests/api/test_cockpit_suggestions.py",
         "tests/api/test_preferences.py"],
    ),
]


def run(paths: list[str], quiet: bool) -> tuple[bool, str]:
    """One pytest process over one group."""
    # No -q here: pyproject already supplies it, and a second one makes -qq,
    # which suppresses the very summary line this function reads.
    argv = [sys.executable, "-m", "pytest", *paths, "-p", "no:randomly",
            "--no-header"]
    done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                          env={**_env()})
    tail = (done.stdout or done.stderr).strip().splitlines()
    summary = next((line for line in reversed(tail)
                    if "passed" in line or "failed" in line or "error" in line),
                   "no summary")
    if not quiet and done.returncode != 0:
        print("\n".join(tail[-40:]))
    return done.returncode == 0, summary


def _env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", metavar="PATH",
                    help="write the result for a later comparison")
    ap.add_argument("--compare", metavar="PATH",
                    help="a previous --json result; report what CHANGED")
    ap.add_argument("--only", metavar="GROUP", default="",
                    help="run one group by name")
    ap.add_argument("--quiet", action="store_true",
                    help="summaries only, no pytest output")
    args = ap.parse_args()

    groups = [g for g in GROUPS if not args.only or g[0] == args.only]
    if not groups:
        print(f"no group named {args.only!r}; "
              f"try one of: {', '.join(g[0] for g in GROUPS)}")
        return 2

    # Line-buffered: this is watched while it runs, often over a slow link at
    # an unsociable hour, and a tool that prints nothing for six minutes is
    # indistinguishable from a tool that has hung.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):  # pragma: no cover - odd stdout
        pass

    print("PROTECTED REGRESSION BASELINE")
    print("=" * 72)
    results: dict[str, dict[str, object]] = {}
    started = time.time()

    for name, why, paths in groups:
        at = time.time()
        ok, summary = run(paths, args.quiet)
        took = time.time() - at
        results[name] = {"ok": ok, "summary": summary, "seconds": round(took, 1)}
        print(f"{'PASS' if ok else 'FAIL'}  {name:<26} {summary}  [{took:.0f}s]")
        if not ok:
            print(f"      protects: {why}")

    total = time.time() - started
    failed = [n for n, r in results.items() if not r["ok"]]
    print("=" * 72)
    print(f"{len(groups) - len(failed)}/{len(groups)} groups green "
          f"in {total / 60:.1f} minutes")

    if args.compare:
        before = json.loads(Path(args.compare).read_text())["groups"]
        broke = [n for n, r in results.items()
                 if not r["ok"] and before.get(n, {}).get("ok")]
        fixed = [n for n, r in results.items()
                 if r["ok"] and before.get(n) and not before[n]["ok"]]
        still = [n for n in failed if not before.get(n, {}).get("ok", True)]
        print("-" * 72)
        print(f"REGRESSED BY THIS CHANGE: {', '.join(broke) if broke else '0'}")
        if still:
            print(f"already red before it:    {', '.join(still)}")
        if fixed:
            print(f"fixed by it:              {', '.join(fixed)}")
        # A group that was green and is now red is the only failing exit.
        if broke:
            return 1

    if args.json:
        Path(args.json).write_text(json.dumps(
            {"head": _head(), "seconds": round(total, 1), "groups": results},
            indent=2) + "\n")
        print(f"wrote {args.json}")

    return 1 if failed and not args.compare else 0


def _head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
