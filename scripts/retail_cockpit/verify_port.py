#!/usr/bin/env python3
"""Is the ported engine still the engine that was ported?

    .venv/bin/python scripts/retail_cockpit/verify_port.py

`docs/retail_cockpit/PORTED_FILES.md` records a SHA-256 for every file
carried over from the frozen AdvancedCockpit. This recomputes all of them and
says which, if any, have moved -- and separately lists the protected-core
diff against the source commit, because "nothing changed" and "only the two
approved things changed" are different claims and only the second one is
true.

Exit 0 when every ported file matches its recorded hash apart from the
approved core changes, and the core diff is exactly those files.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "docs" / "retail_cockpit" / "PORTED_FILES.md"
SOURCE = "19dc143c433eff190de7d304e53b7e941c96735b"

#: The two changes that were approved, and the only ones allowed.
APPROVED = ("backend/cockpit_v4/catalog.py", "backend/cockpit_v4/domains.py")

#: The one FRONTEND file that is no longer byte-identical to the source, and
#: why. It is not exempted from anything: `PORTED_FILES.md` records its
#: current hash, so it is checked exactly as strictly as the other 290 and a
#: further edit still fails. It is named here so the report says what the
#: port is rather than printing "unchanged" over a file that moved.
FRONTEND_EXCEPTION = {
    "frontend/src/components/cockpit-v4/attention-panel.tsx":
        "F1 -- the ECL-highlights caption names the dimension the server "
        "cut the cards by, per book, instead of the corporate one",
}

_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`?([0-9a-f]{8,64})`?\s*\|")


def recorded() -> dict[str, str]:
    if not RECORD.exists():
        raise SystemExit(f"no record at {RECORD}")
    out: dict[str, str] = {}
    for line in RECORD.read_text(encoding="utf-8").splitlines():
        match = _ROW.match(line.strip())
        if match:
            out[match.group(1)] = match.group(2)
    return out


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def core_diff() -> list[str]:
    done = subprocess.run(
        ["git", "diff", "--name-only", SOURCE, "--",
         "backend/cockpit_v4", "backend/cockpit_agentic"],
        cwd=str(ROOT), capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit(f"the source commit {SOURCE[:12]} is not in this "
                         f"clone, so the port cannot be verified")
    return sorted(x for x in done.stdout.split() if x)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    known = recorded()
    if not known:
        raise SystemExit(f"{RECORD} records no file hashes")

    missing: list[str] = []
    moved: list[tuple[str, str, str]] = []
    for name, want in sorted(known.items()):
        path = ROOT / name
        if not path.exists():
            missing.append(name)
            continue
        got = digest(path)
        if not got.startswith(want):
            moved.append((name, want, got[:len(want)]))

    changed = core_diff()
    unexpected = [f for f in changed if f not in APPROVED]
    # A file that moved AND is one of the two approved changes is expected.
    surprising = [m for m in moved if m[0] not in APPROVED]

    if not args.quiet:
        print(f"ported files recorded   {len(known)}")
        print(f"  unchanged             "
              f"{len(known) - len(moved) - len(missing)}")
        print(f"  changed               {len(moved)} "
              f"({', '.join(m[0] for m in moved) or 'none'})")
        print(f"  missing               {len(missing)}")
        print(f"protected-core diff     {changed or 'none'}")
        print(f"  approved              {list(APPROVED)}")
        for name, why in sorted(FRONTEND_EXCEPTION.items()):
            print(f"frontend exception      {name}")
            print(f"  {why}")
        print()

    findings: list[str] = []
    for name in FRONTEND_EXCEPTION:
        if name not in known:
            findings.append(f"{name} is declared a frontend exception but "
                            f"{RECORD.name} records no hash for it, so "
                            f"nothing is checking it")
    if missing:
        findings.append(f"{len(missing)} ported file(s) are gone: "
                        f"{missing[:5]}")
    for name, want, got in surprising:
        findings.append(f"{name} no longer matches the port "
                        f"({want} -> {got})")
    for name in unexpected:
        findings.append(f"{name} is a protected-core change that was never "
                        f"approved")

    print("PORT VERIFIED" if not findings else "PORT NOT VERIFIED")
    for line in findings:
        print(f"  - {line}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
