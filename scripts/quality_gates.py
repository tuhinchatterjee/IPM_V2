"""
The quality gates, run in order. §131.

    "Run sequentially … No live provider calls in Claude Code."

Why a script rather than a checklist
-------------------------------------
Twenty-two gates run by hand are twenty-two gates somebody skips one of, and
the one they skip is whichever failed last time. Run as a script they either
all pass or the run stops with the name of the one that did not.

Sequential on purpose. A parallel run finishes faster and reports four
failures at once, three of which are consequences of the first — and somebody
spends the afternoon on the third.

What "no live provider calls" means here
------------------------------------------
Every gate below is deterministic. The live smoke test and the sealed
certification are NOT in this list: they cost money, they need a key, and a
gate that spends credits is one nobody runs before pushing. They are named in
`DEFERRED` so their absence is visible rather than assumed.

Usage
-----
    python -m scripts.quality_gates            # everything available here
    python -m scripts.quality_gates --list     # what would run, in order
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv" / "bin"
PYTHON = str(VENV / "python") if (VENV / "python").exists() else sys.executable
RUFF = str(VENV / "ruff") if (VENV / "ruff").exists() else "ruff"


@dataclass
class Gate:
    """One gate: what it checks, how to run it, and whether it can run here."""

    name: str
    checks: str
    command: list[str]
    #: A gate that cannot run in this environment is SKIPPED with a reason,
    #: never quietly passed. The whole point of the list is that a green run
    #: means something.
    needs: str = ""
    cwd: Path = field(default=ROOT)

    def available(self) -> tuple[bool, str]:
        if not self.needs:
            return True, ""
        if self.needs == "node":
            return (bool(shutil.which("npm")),
                    "npm is not on the path")
        if self.needs == "docker":
            return (bool(shutil.which("docker")),
                    "docker is not on the path")
        if self.needs == "powershell":
            return (bool(shutil.which("pwsh") or shutil.which("powershell")),
                    "no PowerShell runtime")
        if self.needs == "database":
            from tests.conftest import database_available

            return database_available(), "no platform database"
        return True, ""


#: §131's list, in §131's order.
GATES: tuple[Gate, ...] = (
    Gate("ruff", "Python lint and import order",
         [RUFF, "check", "backend/", "tests/", "intelligence_factory/",
          "scripts/"]),
    Gate("pytest", "The complete backend suite",
         [PYTHON, "-m", "pytest", "-q"]),
    Gate("powershell", "The PowerShell scripts parse",
         [PYTHON, "-m", "pytest", "-q", "tests/scripts/"],
         needs="powershell"),
    Gate("typescript", "The front end typechecks",
         ["npm", "run", "typecheck"], needs="node", cwd=ROOT / "frontend"),
    Gate("eslint", "The front end lints",
         ["npm", "run", "lint"], needs="node", cwd=ROOT / "frontend"),
    Gate("frontend-tests", "The front-end unit tests",
         ["npm", "test"], needs="node", cwd=ROOT / "frontend"),
    Gate("next-build", "A production build of the front end",
         ["npm", "run", "build"], needs="node", cwd=ROOT / "frontend"),
    Gate("migrations-empty", "Migrations run from an empty database",
         [PYTHON, "-m", "pytest", "-q", "tests/runtime/", "-k", "migration"],
         needs="database"),
    Gate("teaching", "The teaching library and its governance",
         [PYTHON, "-m", "pytest", "-q", "tests/teaching/"]),
    Gate("judgment", "The analytical judgment engines",
         [PYTHON, "-m", "pytest", "-q", "tests/judgment/"]),
    Gate("factory", "The Intelligence Factory and the corpora",
         [PYTHON, "-m", "pytest", "-q", "tests/factory/"]),
    Gate("studio", "The AI Intelligence Studio API",
         [PYTHON, "-m", "pytest", "-q", "tests/studio/"]),
    Gate("holdout-isolation",
         "The backend cannot import the Intelligence Factory",
         [PYTHON, "-m", "pytest", "-q", "tests/factory/test_isolation.py"]),
    Gate("release-manifest", "The release manifest and its gate",
         [PYTHON, "-m", "pytest", "-q",
          "tests/factory/test_release_manifest.py",
          "tests/teaching/test_release_and_disclosure.py"]),
    Gate("docker-config", "The Compose file is valid",
         ["docker", "compose", "config", "-q"], needs="docker"),
)

#: Gates that exist and are deliberately NOT in the list above, so their
#: absence from a green run is visible rather than assumed.
DEFERRED: tuple[tuple[str, str], ...] = (
    ("live smoke test",
     "spends credits and needs a provider key; run "
     "scripts/verify-live-ai.ps1 -Mode quick"),
    ("sealed certification",
     "spends real money; run python -m intelligence_factory.certify "
     "--certify --confirm"),
    ("browser acceptance",
     "needs a running stack and a browser; run against localhost:3000"),
    ("docker build and health",
     "needs a Docker daemon with network access"),
)


def run(gate: Gate) -> dict[str, Any]:
    ok, why = gate.available()
    if not ok:
        return {"gate": gate.name, "status": "SKIPPED", "why": why,
                "seconds": 0.0}
    started = time.perf_counter()
    try:
        finished = subprocess.run(gate.command, cwd=gate.cwd, check=False,
                                  capture_output=True, text=True,
                                  timeout=3600)
    except FileNotFoundError as e:
        return {"gate": gate.name, "status": "SKIPPED", "why": str(e),
                "seconds": 0.0}
    elapsed = round(time.perf_counter() - started, 1)
    if finished.returncode == 0:
        return {"gate": gate.name, "status": "PASSED", "seconds": elapsed}
    tail = (finished.stdout or "")[-2000:] + (finished.stderr or "")[-2000:]
    return {"gate": gate.name, "status": "FAILED", "seconds": elapsed,
            "output": tail}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="Print the gates in order and exit.")
    parser.add_argument("--only", default="",
                        help="Run one gate by name.")
    args = parser.parse_args(argv)

    if args.list:
        for gate in GATES:
            print(f"{gate.name:20s} {gate.checks}")
        print("\nDeliberately not run here:")
        for name, why in DEFERRED:
            print(f"{name:20s} {why}")
        return 0

    chosen = [g for g in GATES if not args.only or g.name == args.only]
    if not chosen:
        print(f"No gate named {args.only!r}.", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for gate in chosen:
        result = run(gate)
        results.append(result)
        mark = {"PASSED": "ok", "SKIPPED": "--", "FAILED": "FAIL"}[
            result["status"]]
        print(f"[{mark:4s}] {gate.name:20s} {gate.checks}"
              + (f"  ({result['why']})" if result.get("why") else "")
              + (f"  {result['seconds']}s" if result.get("seconds") else ""))
        if result["status"] == "FAILED":
            # Stop at the first failure. Reporting four at once reports three
            # consequences of the first, and somebody spends the afternoon on
            # the third.
            print("\n" + (result.get("output") or ""), file=sys.stderr)
            print(f"\nStopped at {gate.name}.", file=sys.stderr)
            return 1

    skipped = [r for r in results if r["status"] == "SKIPPED"]
    print(f"\n{len(results) - len(skipped)} gates passed"
          + (f", {len(skipped)} skipped: "
             + ", ".join(r["gate"] for r in skipped) if skipped else "."))
    print("\nNot run here (they cost money or need a live stack):")
    for name, why in DEFERRED:
        print(f"  {name}: {why}")
    return 0


if __name__ == "__main__":  # pragma: no cover - a command-line entry point
    raise SystemExit(main())
