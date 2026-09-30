#!/usr/bin/env python3
"""The Guided Risk Workspace round's protected baseline: captured at H2, checked forever.

    python scripts/guided_workspace/protected_baseline.py --write   # P0 only
    python scripts/guided_workspace/protected_baseline.py --check   # every gate

`scripts/whatif/protected_hashes.py` compares against the ACCEPTED baseline
`245c50e` and its manifest was captured in another container, whose Parquet
writer stamped different bytes into the published books (see
`docs/cockpit_v4/RELEASE_HISTORY.md`, "Checking a release on your own
machine"). Its `--check` therefore reports every data file as CHANGED here even
though nothing was edited, which makes it unable to detect a change THIS round
makes. It is kept, run and reported unchanged -- it is not regenerated.

This tool answers the narrower question the round needs: relative to the exact
H2 checkpoint `feb80f58` and the books published in THIS container at P0, which
protected files did this round change? It reuses the very same protected
groups (imported, not copied) so the two tools cannot disagree about what
"protected" means, and it never broadens an allowlist: every difference is
printed, and the justification lives in
`docs/guided_workspace/PROTECTED_EXTENSION_MAP.md`.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "whatif"))

import protected_hashes as ph  # noqa: E402  - the one definition of "protected"

#: The H2 checkpoint this round starts from. Never amended, never moved.
BASELINE = "feb80f58982addf6e9474200b22451d1e303d276"
MANIFEST = "docs/guided_workspace/PROTECTED_FILES_H2.sha256"


def render(groups: dict[str, list[tuple[str, str]]]) -> str:
    total = sum(len(rows) for rows in groups.values())
    lines = [
        "# Protected files at the H2 checkpoint, captured before any P1 edit",
        "",
        f"Commit `{BASELINE}` (claude/advanced-cockpit-whatif-h2-uat-fix).",
        "Data files are the books published in this container at P0.",
        "",
        f"{total} files.",
        "",
        "Verify with `scripts/guided_workspace/protected_baseline.py --check`.",
        "Every difference must be justified in",
        "`docs/guided_workspace/PROTECTED_EXTENSION_MAP.md` or it is a defect.",
        "",
    ]
    for title, rows in groups.items():
        lines += [f"## {title} ({len(rows)} files)", ""]
        lines += [f"{sha}  {rel}" for sha, rel in rows]
        lines.append("")
    return "\n".join(lines) + "\n"


def stored(root: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (root / MANIFEST).read_text().splitlines():
        parts = line.split("  ", 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[parts[1].strip()] = parts[0]
    return out


def diff(root: pathlib.Path) -> tuple[list[str], list[str], list[str]]:
    now = {rel: sha for rows in ph.collect(root).values() for sha, rel in rows}
    then = stored(root)
    changed = sorted(p for p in now if p in then and now[p] != then[p])
    removed = sorted(p for p in then if p not in now)
    added = sorted(p for p in now if p not in then)
    return changed, removed, added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.write:
        if (ROOT / MANIFEST).exists():
            print(f"{MANIFEST} exists; the H2 baseline is captured once and "
                  f"never rewritten.", file=sys.stderr)
            return 2
        (ROOT / MANIFEST).write_text(render(ph.collect(ROOT)))
        print(f"wrote {MANIFEST}")
        return 0
    changed, removed, added = diff(ROOT)
    for label, rows in (("CHANGED", changed), ("REMOVED", removed),
                        ("ADDED", added)):
        for rel in rows:
            print(f"{label:8} {rel}")
    print(f"\n{len(changed)} changed, {len(removed)} removed, {len(added)} "
          f"added against H2 {BASELINE[:12]}.")
    return 1 if (changed or removed or added) else 0


if __name__ == "__main__":
    raise SystemExit(main())
