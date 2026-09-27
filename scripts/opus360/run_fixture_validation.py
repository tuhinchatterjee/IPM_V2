#!/usr/bin/env python3
"""
§27 gate: prove the harness before any paid call.

Runs tests/opus360 (the ten fixture scenarios through the real engine plus the
harness unit tests) and writes artifacts/opus360/fixtures/fixture_validation.json
with the SHA-256 of the harness source tree it validated. `run_certification.py
--live` refuses to start unless that file exists, every test passed, and the
harness tree hash still matches -- so a harness edited after validation cannot
spend money.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "artifacts" / "opus360" / "fixtures"


def harness_tree_sha() -> str:
    digest = hashlib.sha256()
    files = sorted([*ROOT.joinpath("scripts/opus360").rglob("*.py"),
                    *ROOT.joinpath("config/opus360").glob("*"),
                    *ROOT.joinpath("tests/opus360").rglob("*.py")])
    for f in files:
        if f.is_file() and "__pycache__" not in f.parts:
            digest.update(str(f.relative_to(ROOT)).encode())
            digest.update(f.read_bytes())
    return digest.hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    junit = OUT / "fixture_validation.junit.xml"
    done = subprocess.run([sys.executable, "-m", "pytest", "tests/opus360", "-p", "no:cacheprovider",
                           f"--junitxml={junit}"], cwd=ROOT, capture_output=True, text=True, timeout=3600)
    cases = {}
    if junit.exists():
        for tc in ET.parse(junit).getroot().iter("testcase"):
            status = "passed"
            for child in tc:
                if child.tag in ("failure", "error"):
                    status = child.tag
                elif child.tag == "skipped":
                    status = "skipped"
            cases[f"{tc.get('classname')}::{tc.get('name')}"] = status
    passed = sum(1 for s in cases.values() if s == "passed")
    ok = bool(cases) and passed == len(cases) and done.returncode == 0
    result = {"ok": ok, "tests": len(cases), "passed": passed,
              "not_passed": {k: v for k, v in cases.items() if v != "passed"},
              "harness_tree_sha256": harness_tree_sha(), "python": sys.version.split()[0],
              "platform_system": platform.system(), "platform": platform.platform(),
              "validated_at": datetime.now(UTC).isoformat(), "cases": cases,
              "pytest_tail": done.stdout[-1500:]}
    (OUT / "fixture_validation.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"fixture validation {'PASS' if ok else 'FAIL'}: {passed}/{len(cases)} tests; "
          f"harness tree {result['harness_tree_sha256'][:16]}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
