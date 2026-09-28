#!/usr/bin/env python3
"""Refuse to start a UAT that would demonstrate the wrong thing.

A presentation is the one place a wrong revision or a half-built candidate
costs the most, and the failure looks like a product defect rather than a
setup mistake. So every precondition is checked BEFORE anything is started,
each one is reported by name, and any failure is a refusal rather than a
warning nobody reads on the way past.

Checked, in order:

1. **The revision.** A frozen candidate is a TAG, so that is what this pins
   to: `EXPECTED_TAG` below. A HEAD that is not that tag's commit is refused
   with both hashes printed, and a tag that does not exist yet is refused
   too -- an unfrozen candidate is exactly the thing a presentation must not
   be run from by accident. `--any-revision` skips the check deliberately
   and says so in the output, so a transcript can never claim a revision it
   did not run. Pinning to a tag rather than to a literal hash is what keeps
   this file from having to name the commit that contains it.
2. **The interpreter.** The candidate needs `.venv-whatif`; started with the
   accepted one it would run with Method 2 quietly unavailable.
3. **The data.** Both candidate releases published, and each one's
   fingerprint matching what this file expects.
4. **The models.** Both emulator artifact sets present, with their gate
   verdicts read out -- including Retail's FAILED G4, because a presenter
   who does not know that is a presenter about to be surprised by it.
5. **The credential.** PRESENT or MISSING, by name of the variable only. The
   key itself is never read, printed, logged or written anywhere.

Nothing here starts a server. `START_ADVANCEDCOCKPIT_WHATIF_UAT.command`
runs this first and hands over to `start_candidate.py` only on a zero exit.

    .venv-whatif/bin/python scripts/whatif/uat_preflight.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

#: The frozen candidate this UAT is for. A tag, not a hash: the commit that
#: carries this file cannot name its own hash, and a candidate is frozen by
#: being tagged. Change it deliberately, in the same commit that changes what
#: the UAT demonstrates.
EXPECTED_TAG = "whatif-candidate-h1"

#: The H2 remediation branch this preflight also serves. Until an H2
#: candidate is frozen there is no H2 tag, so `--any-revision` is the
#: documented way to run a pre-freeze UAT, and it says so in the output.
H2_BRANCH = "claude/advanced-cockpit-whatif-h2-uat-fix"

#: Each book's candidate release and the fingerprint it must carry. A release
#: id is a name; the fingerprint is what two builds cannot share.
EXPECTED: dict[str, tuple[str, str]] = {
    "corporate": ("v4-whatif-corporate-20q-s1", "3b101bd41465fbe1"),
    "retail": ("v4-whatif-retail-20m-s1", "98b494ae2721bd53"),
}

OK = "  ok   "
BAD = "  REFUSED  "


def revision(*, enforce: bool) -> list[str]:
    """HEAD must be the frozen candidate's tag, or the run is refused."""
    def _git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=str(ROOT),
                              capture_output=True, text=True,
                              check=True).stdout.strip()

    try:
        head = _git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"{BAD}the revision could not be read: {exc}"]

    try:
        wanted = _git("rev-parse", f"{EXPECTED_TAG}^{{commit}}")
    except (OSError, subprocess.CalledProcessError):
        wanted = ""

    if not enforce:
        against = wanted[:12] if wanted else f"{EXPECTED_TAG} (not created)"
        print(f"{OK}revision {head[:12]} (NOT CHECKED: --any-revision was "
              f"passed, and this UAT is for {against})")
        return []

    if not wanted:
        return [f"{BAD}the tag {EXPECTED_TAG} does not exist in this "
                f"checkout, so there is no frozen candidate to run. Fetch "
                f"the tag, or -- if you are running the remediation branch "
                f"{H2_BRANCH}, which is deliberately NOT frozen -- pass "
                f"--any-revision and say so in the evidence."]
    if head != wanted:
        return [f"{BAD}this checkout is at {head[:12]} and {EXPECTED_TAG} is "
                f"{wanted[:12]}. Check out the tag, or pass --any-revision "
                f"and say so in the evidence."]
    print(f"{OK}revision {head[:12]}, which is {EXPECTED_TAG}")
    return []



def required_python() -> tuple[int, int]:
    """The interpreter floor, READ FROM `pyproject.toml` rather than pinned.

    A version hardcoded here would drift away from the one the project
    actually declares, and the drift would only show up on someone's Mac.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'requires-python\s*=\s*"[^0-9]*([0-9]+)\.([0-9]+)',
                      text)
    if not found:
        return (3, 12)
    return (int(found.group(1)), int(found.group(2)))


def python_version() -> list[str]:
    """Refuse an interpreter older than the project's declared floor."""
    want = required_python()
    have = sys.version_info[:2]
    if have < want:
        return [f"{BAD}this interpreter is Python {have[0]}.{have[1]} and "
                f"pyproject.toml requires >= {want[0]}.{want[1]}. Rebuild "
                f"the candidate environment on it:\n"
                f"    python{want[0]}.{want[1]} -m venv --system-site-packages "
                f".venv-whatif\n"
                f"    .venv-whatif/bin/pip install -r requirements-whatif.txt"]
    print(f"{OK}python {have[0]}.{have[1]} (>= {want[0]}.{want[1]})")
    return []


def frontend(root: Path | None = None) -> list[str]:
    """The UI must be installed BEFORE anything is started.

    `npm run dev` resolves `next` from `frontend/node_modules/.bin`. Without
    it the UI child dies with `sh: next: command not found` -- after the API
    is already up, so the operator gets a half-started system and a browser
    that will not load. H1 checked neither, and a clean Mac worktree hit it.
    """
    base = Path(root) if root is not None else ROOT
    binary = base / "frontend" / "node_modules" / ".bin" / "next"
    if not binary.exists():
        return [f"{BAD}{binary} is missing, so the UI cannot start. "
                f"Install the frontend dependencies first:\n"
                f"    npm ci --prefix frontend"]
    print(f"{OK}frontend dependencies present (node_modules/.bin/next)")
    return []


def interpreter() -> list[str]:
    venv = ROOT / ".venv-whatif"
    # `sys.prefix`, NOT `sys.executable`. A venv's `bin/python` is a symlink to
    # the system interpreter, so resolving the executable walks out of the
    # venv and lands in /usr -- which made this refuse the very interpreter it
    # was asking for. `sys.prefix` is what the venv itself sets.
    if Path(sys.prefix).resolve() != venv.resolve():
        return [f"{BAD}this is {sys.executable}. The candidate runs from "
                f"{venv}/bin/python; the accepted interpreter has none of "
                f"the ML libraries and Method 2 would be silently "
                f"unavailable."]
    missing = []
    for library in ("xgboost", "lightgbm", "sklearn", "shap", "pandas"):
        try:
            __import__(library)
        except ImportError:
            missing.append(library)
    if missing:
        return [f"{BAD}the candidate environment cannot import "
                f"{', '.join(missing)}. Rebuild it:\n"
                f"    .venv-whatif/bin/pip install --ignore-installed "
                f"-r requirements-whatif.txt"]
    print(f"{OK}interpreter {sys.executable}")
    return []


def data() -> list[str]:
    from backend.cockpit_v4 import lake

    problems: list[str] = []
    for book, (release_id, fingerprint) in sorted(EXPECTED.items()):
        if not lake.exists(release_id):
            problems.append(
                f"{BAD}{book}: {release_id} is not published. Build it:\n"
                f"    .venv-whatif/bin/python "
                f"scripts/whatif/seed_candidate.py --domain {book}")
            continue
        got = str(lake.fingerprint(release_id) or "")
        if not got.startswith(fingerprint):
            problems.append(
                f"{BAD}{book}: {release_id} carries fingerprint "
                f"{got[:16]} and this UAT expects {fingerprint}. Same name, "
                f"different numbers -- rebuild or check out the matching "
                f"revision.")
            continue
        manifest = lake.read_manifest(release_id)
        periods = manifest.get("reporting_periods") or []
        print(f"{OK}{book:10} {release_id}  {got[:16]}  "
              f"{len(periods)} periods  "
              f"latest {periods[-1] if periods else '?'}")
    return problems


def models() -> list[str]:
    problems: list[str] = []
    for book in sorted(EXPECTED):
        home = ROOT / "artifacts" / "whatif" / book
        manifest = home / "blend.json"
        if not manifest.exists():
            problems.append(
                f"{BAD}{book}: no emulator is published. Train it:\n"
                f"    .venv-whatif/bin/python "
                f"scripts/whatif/train_emulator.py --domain {book}")
            continue
        body = json.loads(manifest.read_text(encoding="utf-8"))
        absent = [name for name in body.get("component_hashes", {})
                  if not (home / f"{name}.pkl").exists()]
        if absent:
            problems.append(
                f"{BAD}{book}: {', '.join(absent)} is named in blend.json "
                f"and is not on disk. Retrain.")
            continue
        gates = body.get("gates") or {}
        failed = sorted(name for name, gate in gates.items()
                        if not gate.get("passed"))
        verdict = ("every gate passed" if not failed else
                   f"FAILED {', '.join(failed)}")
        print(f"{OK}{book:10} {body.get('model_version')}  {verdict}")
        if failed:
            # NOT a refusal. A book whose Method 2 failed its gates is a book
            # whose Method 2 is correctly unavailable in the product, and
            # that is part of what this UAT demonstrates. It is printed so
            # nobody discovers it from the audience.
            for name in failed:
                gate = gates[name]
                print(f"         {name}: {gate.get('what')} measured "
                      f"{gate.get('measured'):.4f} against "
                      f"{gate.get('threshold'):.4f} -- Method 2 is "
                      f"UNAVAILABLE for {book} and the product says so")
    return problems


def credential() -> list[str]:
    """PRESENT or MISSING, by variable name. The key is never touched."""
    from backend.cockpit_v4 import config as config_mod
    from backend.cockpit_v4 import service

    status = service.credential_status()
    print(f"{OK}provider credential {status} "
          f"({config_mod.CREDENTIAL_VAR})")
    if status != "PRESENT":
        print("         A live-provider UAT needs this set. Without it the "
              "candidate starts and refuses every analytical turn at "
              "preflight rather than answering from a stub, which is the "
              "honest failure -- but it is not a live UAT.")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--any-revision", action="store_true",
                        help="skip the revision check and say so in the "
                             "output")
    args = parser.parse_args()

    print("\nWhat-If UAT preflight")
    print("─" * 60)
    problems: list[str] = []
    problems += revision(enforce=not args.any_revision)
    problems += interpreter()
    problems += python_version()
    problems += frontend()
    if not problems:
        # The data and model checks import the backend, which needs the
        # candidate interpreter to have been the one that got here.
        os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
        problems += data()
        problems += models()
        problems += credential()

    print("─" * 60)
    if problems:
        for line in problems:
            print(line)
        print("\nNOT STARTED. Fix the above and run this again.")
        return 1
    print("Preflight passed. The candidate may be started.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
