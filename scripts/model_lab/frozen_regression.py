"""
Run the frozen Cockpit V4 test suite UNCHANGED inside the lab, then undo the
evidence files the frozen tests rewrite (OG-11 / BASELINE_PROVENANCE §7),
keeping a diff of what they wrote. Reports pass/fail/skip counts.

    python scripts/model_lab/frozen_regression.py [-- extra pytest args]
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts" / "model_comparison" / "regression"
EVIDENCE = "docs/cockpit_v4/evidence/"


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    log = OUT / f"frozen_pytest_{stamp}.txt"
    extra = argv[argv.index("--") + 1:] if "--" in argv else []
    cmd = [sys.executable, "-m", "pytest", "tests/cockpit_v4", "-p",
           "no:cacheprovider", "-rN", "-o", "addopts=", "-q", *extra]
    with log.open("w") as f:
        rc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT
                            ).returncode
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--", EVIDENCE],
                          capture_output=True, text=True).stdout
    if diff:
        (OUT / f"frozen_tests_evidence_write_{stamp}.diff").write_text(diff)
        subprocess.run(["git", "-C", str(ROOT), "checkout", "--", EVIDENCE],
                       check=True)
    tail = log.read_text()[-600:]
    m = re.search(r"(\d+) passed", tail)
    print(tail.strip().splitlines()[-1] if tail.strip() else "no output")
    print(f"exit={rc} log={log.relative_to(ROOT)} "
          f"evidence_restored={'yes' if diff else 'nothing written'}")
    return 0 if rc == 0 and m else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
