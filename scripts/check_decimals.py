#!/usr/bin/env python
"""The decimal display contract, enforced. §4.

    python scripts/check_decimals.py
    python scripts/check_decimals.py --list-allowed

Two formatters already decide how a number is written down -
`backend.orchestration.figures` and `frontend/src/lib/format.ts`. Both cap
user-facing precision at two decimals. Neither can stop a component writing
`value.toFixed(3)` on its own, and that is how the debris came back the last
three times.

So this scans for the bypass rather than for the symptom. It finds every place
that turns a number into text with more than two decimals, and requires each
one to be either

  * fixed, or
  * on the allowlist below WITH A REASON.

The allowlist is the interesting part. Some high-precision formatting is
correct and must not be "fixed": grounding validation compares a figure in the
prose against the figures in the result, and it does that by generating every
plausible rendering of each value - at six decimals, because a value that
matched only at two would let a hallucinated third decimal through. Rounding
those would not tidy a display, it would weaken a safety check.

Anything not on the list is a defect. A new one fails this script, which is
the point: the contract holds because bypassing it is noisy, not because
everyone remembered.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Python: an f-string or format spec asking for three or more decimals.
_PY = re.compile(r":\.[3-9]\d*f")
#: TypeScript: toFixed(3) or higher, and maximumFractionDigits above two.
_TS = re.compile(r"toFixed\(\s*([3-9]|\d\d+)\s*\)"
                 r"|maximumFractionDigits:\s*([3-9]|\d\d+)")


@dataclass(frozen=True)
class Allowed:
    """One place high precision is correct, and why."""

    path: str
    reason: str
    #: None means every match in the file is allowed for this reason.
    lines: tuple[int, ...] | None = None


#: Paths where more than two decimals is CORRECT. Every entry is a claim that
#: the number never reaches a reader as a figure.
ALLOWLIST: tuple[Allowed, ...] = (
    Allowed(
        "backend/scorecard/metrics.py",
        "Model-validation statistics on the unit interval: AUC, Gini, KS, "
        "PSI, CSI, Brier. These DO reach a reader, at four decimals, and "
        "that is deliberate rather than an oversight. The display contract "
        "governs business figures — money and rates a committee reads as "
        "amounts. A Brier score of 0.0523 shown as 0.05 has lost the "
        "quantity, and a discrimination trend is precisely a question about "
        "the third and fourth decimal: an AUC that moved 0.7179 to 0.7104 "
        "is the finding, and at two decimals both months read 0.72. "
        "Percentages, money and counts in this module go through the "
        "contract as everywhere else."),
    Allowed(
        "backend/scorecard/diagnostics.py",
        "The same statistics, rendered into the diagnostic sentences a "
        "validator reads. Same reasoning as metrics.py: the deterioration "
        "being diagnosed is usually smaller than 0.01."),
    Allowed(
        "backend/orchestration/evidence.py",
        "Grounding validation. Builds every plausible rendering of a computed "
        "value so a figure in the prose can be matched against the result. "
        "Matching at two decimals would let a hallucinated third decimal "
        "through, so the precision here is the safety property."),
    Allowed(
        "backend/orchestration/assembly.py",
        "The same token set as evidence.py, built where the answer is "
        "assembled. Comparison, never display."),
    Allowed(
        "backend/runtime/fingerprint.py",
        "Plan and result fingerprints. The formatted value is a hash input, "
        "never a figure on a screen, and rounding it would make two runs "
        "that computed different numbers fingerprint identically."),
    Allowed(
        "backend/agentic/evaluation.py",
        "Evaluation scores in an internal diagnostic string, read by "
        "engineers in logs and evaluation reports rather than by a credit "
        "officer in an answer."),
    Allowed(
        "backend/climate/",
        "The climate module in full. Model coefficients, fitted constants, "
        "probit pushes and the SVG value formats that render them - a "
        "technical calibration appendix. Verified out of the user path: the "
        "package has no API router, no frontend route and no navigation "
        "entry, so none of these numbers reaches a reader as a figure."),
    Allowed(
        "frontend/src/lib/scorecard-format.ts",
        "Fitted scorecard coefficients, and nothing else. A coefficient is "
        "not a business figure - it is part of the model's specification, "
        "the number somebody re-types to reproduce a score, and §52's "
        "implementation replication is precisely the question of whether "
        "production computes the same score from the same equation. A "
        "coefficient of 0.000412 written as 0.00 cannot answer it. The "
        "module exists so this exemption is one function wide: every rate, "
        "amount and count on the validation screens goes through the "
        "contract as everywhere else."),
    Allowed(
        "backend/ai_context.py",
        "The calibrated constant k in a technical model description, not a "
        "portfolio figure."),
)

#: Where to look. The governed answer path, the API, the exports and the UI.
_SCAN: tuple[tuple[str, str], ...] = (
    ("backend", "*.py"),
    ("frontend/src", "*.ts"),
    ("frontend/src", "*.tsx"),
)

#: Never scanned: tests assert on precision deliberately, and generated or
#: vendored code is not ours to hold to the contract.
_SKIP = ("/tests/", "/test_", "/__tests__/", "/node_modules/", "/.next/",
         "/legacy/", "/__pycache__/")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    text: str


def _allowed_for(path: str) -> Allowed | None:
    for entry in ALLOWLIST:
        if path == entry.path or path.startswith(entry.path):
            return entry
    return None


def scan() -> tuple[list[Finding], list[Finding]]:
    """Every high-precision formatting site, split into defects and allowed."""
    defects: list[Finding] = []
    allowed: list[Finding] = []

    for base, glob in _SCAN:
        for file in sorted((ROOT / base).rglob(glob)):
            relative = file.relative_to(ROOT).as_posix()
            if any(skip in f"/{relative}" for skip in _SKIP):
                continue
            pattern = _PY if file.suffix == ".py" else _TS
            try:
                lines = file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, start=1):
                if not pattern.search(line):
                    continue
                found = Finding(relative, number, line.strip()[:110])
                (allowed if _allowed_for(relative) else defects).append(found)
    return defects, allowed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-allowed", action="store_true",
                        help="print the allowlist and what each entry claims")
    args = parser.parse_args()

    if args.list_allowed:
        for entry in ALLOWLIST:
            print(f"{entry.path}\n    {entry.reason}\n")
        return 0

    defects, allowed = scan()
    print(f"{len(allowed)} high-precision site(s) allowed with a reason; "
          f"{len(defects)} not.")
    if not defects:
        print("OK  every user-facing number goes through the display "
              "contract")
        return 0

    print("\nThese write more than two decimals into something a reader "
          "sees. Route them through the display contract, or add them to "
          "ALLOWLIST with a reason that says why the number never reaches a "
          "reader as a figure.\n")
    for found in defects:
        print(f"  {found.path}:{found.line}\n      {found.text}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
