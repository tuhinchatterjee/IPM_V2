#!/usr/bin/env python3
"""
Run the frozen cockpit regression suite UNCHANGED and record parity evidence.

    .venv/bin/python scripts/opus360/run_frozen_regression.py --label before
    .venv/bin/python scripts/opus360/run_frozen_regression.py --label after \
        --compare artifacts/opus360/regression/before.json

The frozen suite writes some of its own evidence into tracked files under
docs/cockpit_v4/evidence. That is recorded (which files, their diff stat) and
the files are then restored from the frozen commit, so a regression run can
never leave the certification branch dirty. Protected paths are verified
after the run as well.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from cert import FROZEN_COMMIT, protected  # noqa: E402
from cert.paths import ARTIFACTS, ROOT  # noqa: E402


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout


def parse_junit(path: Path) -> dict:
    out = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "passed": 0,
           "cases": {}}
    if not path.exists():
        return out
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        name = f"{case.get('classname')}::{case.get('name')}"
        status = "passed"
        for child in case:
            tag = child.tag
            if tag in ("failure", "error"):
                status = tag
                break
            if tag == "skipped":
                status = "skipped"
        out["cases"][name] = status
    counts = {"passed": 0, "failure": 0, "error": 0, "skipped": 0}
    for status in out["cases"].values():
        counts[status] += 1
    out.update(tests=len(out["cases"]), passed=counts["passed"],
               failures=counts["failure"], errors=counts["error"],
               skipped=counts["skipped"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--compare", default="")
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()

    outdir = ARTIFACTS / "regression"
    outdir.mkdir(parents=True, exist_ok=True)
    junit = outdir / f"{args.label}.junit.xml"
    log = outdir / f"{args.label}.log"
    pre_dirty = git("status", "--porcelain", "--untracked-files=no").strip()
    started = time.time()
    with open(log, "w", encoding="utf-8") as fh:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/cockpit_v4", "-q",
             "-p", "no:cacheprovider", f"--junitxml={junit}",
             "--ignore=tests/cockpit_v4/browser"],
            cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
            timeout=args.timeout, check=False)
    elapsed = time.time() - started
    written = [line[3:] for line in git("status", "--porcelain",
                                        "--untracked-files=no").splitlines()
               if line.strip()]
    written_new = [p for p in written if p not in pre_dirty]
    diffstat = git("diff", "--stat", "--", *written_new) if written_new else ""
    if written_new:
        subprocess.run(["git", "checkout", FROZEN_COMMIT, "--", *written_new],
                       cwd=ROOT, check=False)
    verdict = protected.verify()
    result = parse_junit(junit)
    summary = {
        "label": args.label,
        "finished_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "pytest_exit_code": done.returncode,
        "python": sys.version.split()[0],
        "command": "python -m pytest tests/cockpit_v4 -q -p no:cacheprovider "
                   "--ignore=tests/cockpit_v4/browser",
        "browser_suite": "excluded: needs Node/Next.js UI and Chromium stack; "
                         "the browser is not the system under test",
        "counts": {k: result[k] for k in ("tests", "passed", "failures",
                                          "errors", "skipped")},
        "tracked_files_written_by_suite_and_restored": written_new,
        "diffstat_before_restore": diffstat,
        "protected_manifest_after": verdict.to_dict(),
        "non_passing": {k: v for k, v in result["cases"].items()
                        if v in ("failure", "error")},
        "cases": result["cases"],
    }
    if args.compare:
        base = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        changed = {name: {"before": base["cases"].get(name), "after": status}
                   for name, status in result["cases"].items()
                   if base["cases"].get(name) != status}
        missing = sorted(set(base["cases"]) - set(result["cases"]))
        summary["parity"] = {
            "compared_to": args.compare,
            "identical": not changed and not missing,
            "changed_outcomes": changed, "missing_cases": missing}
    (outdir / f"{args.label}.json").write_text(
        json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("label", "counts",
                                              "tracked_files_written_by_suite_and_restored")}
                     | {"protected_ok": verdict.ok,
                        "parity": summary.get("parity", {}).get("identical")},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
